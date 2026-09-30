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
