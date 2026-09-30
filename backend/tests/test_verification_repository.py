from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3

import pytest

from app.migrations import migrate
from app.verification_contract import capture_contract
from app.verification_repository import VerificationError, VerificationRepository
from test_revision_migrations import legacy


@pytest.fixture
def ledger(legacy):
    path, backup = legacy
    migrate(path, backup, target_version=2)
    requirement = {'key':'page','title':'Page','detail':'','checks':[{'type':'exists','selector':'#page'}]}
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        workspace, = db.execute('SELECT id FROM revision_workspaces WHERE heat_id IS NULL').fetchone()
        # Ledger fixtures only, not physical artifact or browser acceptance.
        db.execute('INSERT INTO revision_artifacts VALUES (?,?,14,1)', ('a'*64,'b'*64))
        db.execute("INSERT INTO revision_records VALUES ('root',?,'project',NULL,?,?,NULL,1)", (workspace,'a'*64,'b'*64))
        db.execute("UPDATE revision_workspaces SET current_revision_id='root' WHERE id=?", (workspace,))
        db.execute('INSERT INTO requirements VALUES (?,?,?,?,?,?,?)', ('requirement','project','page','Page','',json.dumps(requirement['checks']),0))
    arguments = dict(owner='user',workspace_id=workspace,request_id='verification',expected_revision='root',
                     expected_contract=capture_contract([requirement]).digest,policy_digest='c'*64,
                     runner_version='runner-1',budget_seconds=60)
    return path, VerificationRepository(path), arguments


def test_reservation_is_persisted_exact_and_concurrently_idempotent(ledger):
    path, repository, arguments = ledger
    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(lambda _: repository.reserve(**arguments), range(2)))
    assert values[0] == values[1]
    assert values[0].deadline - values[0].created_at == 60
    assert values[0].contract.digest == arguments['expected_contract']
    assert VerificationRepository(path).reserve(**arguments) == values[0]
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM verification_requests').fetchone() == (1,)
        assert db.execute('SELECT count(*) FROM verification_results').fetchone() == (0,)


@pytest.mark.parametrize('changed', [dict(owner='foreign'),dict(expected_revision='other'),
    dict(expected_contract='d'*64),dict(budget_seconds=True),dict(policy_digest='invalid')])
def test_denied_reservation_has_no_ledger_effects(ledger, changed):
    path, repository, arguments = ledger
    with pytest.raises(VerificationError): repository.reserve(**(arguments | changed))
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM verification_requests').fetchone() == (0,)


def test_historical_replay_does_not_retarget_or_extend_expired_request(ledger, monkeypatch):
    path, repository, arguments = ledger
    original = repository.reserve(**arguments)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE requirements SET title='Changed contract'")
    monkeypatch.setattr('app.verification_repository.time.time', lambda: original.deadline+100)
    assert repository.reserve(**arguments) == original
    with pytest.raises(VerificationError, match='verification_conflict'):
        repository.reserve(**(arguments | {'request_id':'new'}))
    with pytest.raises(VerificationError, match='verification_conflict'):
        repository.reserve(**(arguments | {'budget_seconds':61}))


def test_active_run_and_write_contention_deny_admission(ledger):
    path, repository, arguments = ledger
    with sqlite3.connect(path) as db:
        db.execute("UPDATE projects SET active_run_id='run'")
    with pytest.raises(VerificationError, match='verification_conflict'):
        repository.reserve(**arguments)
    with sqlite3.connect(path) as db:
        db.execute('UPDATE projects SET active_run_id=NULL')
    with sqlite3.connect(path) as writer:
        writer.execute('BEGIN IMMEDIATE')
        with pytest.raises(VerificationError, match='verification_unavailable'):
            VerificationRepository(path,lock_timeout=0.05).reserve(**arguments)
    assert repository.reserve(**arguments).id == 'verification'


def test_schema_drift_after_open_fails_without_insert(ledger):
    path, repository, arguments = ledger
    with sqlite3.connect(path) as db:
        db.execute('ALTER TABLE projects ADD COLUMN drift TEXT')
    with pytest.raises(VerificationError, match='verification_unavailable'):
        repository.reserve(**arguments)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM verification_requests').fetchone() == (0,)


def report(passed=True, note='observed'):
    return [{'key':'page','checkIndex':0,'passed':passed,'note':note}]


def test_report_concurrent_replay_is_immutable_and_survives_expiry(ledger, monkeypatch):
    path, repository, arguments = ledger
    request = repository.reserve(**arguments)
    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(lambda _: repository.record_report(owner='user', request_id=request.id, results=report()), range(2)))
    assert values[0] == values[1] and values[0].outcome == 'passed'
    assert (values[0].total, values[0].passed) == (1,1)
    monkeypatch.setattr('app.verification_repository.time.time', lambda: request.deadline+100)
    assert VerificationRepository(path).record_report(owner='user',request_id=request.id,results=report()) == values[0]
    for changed in [report(False), report(note='changed evidence')]:
        with pytest.raises(VerificationError, match='verification_conflict'):
            repository.record_report(owner='user',request_id=request.id,results=changed)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM verification_results').fetchone() == (1,)
        assert db.execute('SELECT count(*) FROM release_records').fetchone() == (0,)


@pytest.mark.parametrize('case', ['foreign', 'missing', 'incomplete', 'duplicate', 'nonboolean', 'expired', 'clock-reversed'])
def test_invalid_report_does_not_create_evidence(ledger, monkeypatch, case):
    path, repository, arguments = ledger
    request = repository.reserve(**arguments)
    owner, request_id, results = 'user', request.id, report()
    if case == 'foreign': owner = 'foreign'
    elif case == 'missing': request_id = 'missing'
    elif case == 'incomplete': results = []
    elif case == 'duplicate': results *= 2
    elif case == 'nonboolean': results[0]['passed'] = 1
    elif case == 'expired': monkeypatch.setattr('app.verification_repository.time.time', lambda: request.deadline+1)
    else: monkeypatch.setattr('app.verification_repository.time.time', lambda: request.created_at-1)
    with pytest.raises(VerificationError):
        repository.record_report(owner=owner,request_id=request_id,results=results)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM verification_results').fetchone() == (0,)


def test_report_uses_captured_contract_after_current_contract_changes(ledger):
    path, repository, arguments = ledger
    request = repository.reserve(**arguments)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE requirements SET checks_json='[]'")
    result = repository.record_report(owner='user',request_id=request.id,results=report(False))
    assert result.outcome == 'failed' and result.contract_digest == request.contract.digest
    assert result.revision_id == 'root'


def test_process_exit_before_report_commit_leaves_no_partial_evidence(ledger):
    import os
    from pathlib import Path
    import subprocess
    import sys
    path, repository, arguments = ledger
    request = repository.reserve(**arguments)
    script = '''
import os,sys
from pathlib import Path
from contextlib import contextmanager
from app.verification_repository import VerificationRepository
repository=VerificationRepository(Path(sys.argv[1]))
original=repository._transaction
@contextmanager
def crash():
    with original() as db:
        yield db
        os._exit(43)
repository._transaction=crash
repository.record_report(owner='user',request_id='verification',results=[{'key':'page','checkIndex':0,'passed':True,'note':'observed'}])
'''
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    result = subprocess.run([sys.executable,'-c',script,str(path)],env=env,capture_output=True,timeout=15)
    assert result.returncode == 43, result.stderr
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM verification_results').fetchone() == (0,)
    assert repository.record_report(owner='user',request_id=request.id,results=report()).outcome == 'passed'
