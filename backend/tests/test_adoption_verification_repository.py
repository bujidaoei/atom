"""A real adopted head remains a valid immutable verification target on v12."""
import json
import sqlite3
import time

import pytest

from app.adoption_repository import AdoptionRepository
from app.revisions import RevisionRepository
from app.verification_contract import capture_contract
from app.verification_repository import VerificationError, VerificationRepository
from test_adoption_repository import Store, adopt, prepared
from test_revision_migrations import legacy


@pytest.fixture
def adopted(prepared):
    path, main, _, payload, artifact = prepared
    receipt = adopt(AdoptionRepository(path), Store(artifact.key, payload))
    requirement = {'key': 'page', 'title': 'Page', 'detail': '',
                   'checks': [{'type': 'exists', 'selector': '#page'}]}
    with sqlite3.connect(path) as db:
        db.execute('INSERT INTO requirements VALUES (?,?,?,?,?,?,?)',
                   ('requirement', 'project', 'page', 'Page', '',
                    json.dumps(requirement['checks']), 0))
    intent = dict(owner='user', workspace_id=main, request_id='verify-adopted',
                  expected_revision=receipt.revision_id,
                  expected_contract=capture_contract([requirement]).digest,
                  policy_digest='c' * 64, runner_version='runner-1', budget_seconds=60)
    return path, receipt, intent


def test_adopted_head_reserves_and_records_exact_report(adopted):
    path, receipt, intent = adopted
    repository = VerificationRepository(path)
    request = repository.reserve(**intent)
    assert request.revision_id == receipt.revision_id
    results = [{'key': 'page', 'checkIndex': 0, 'passed': True, 'note': 'observed'}]
    result = repository.record_report(owner='user', request_id=request.id, results=results)
    assert result.revision_id == receipt.revision_id and result.outcome == 'passed'
    assert VerificationRepository(path).reserve(**intent) == request
    assert repository.record_report(owner='user', request_id=request.id, results=results) == result
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT revision_id FROM verification_requests').fetchone() == (receipt.revision_id,)
        assert db.execute('SELECT revision_id FROM verification_results').fetchone() == (receipt.revision_id,)
        assert db.execute('SELECT adoption_id FROM revision_records WHERE id=?',
                          (receipt.revision_id,)).fetchone() == ('command',)
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_stale_parent_and_foreign_owner_cannot_reserve(adopted):
    path, _, intent = adopted
    repository = VerificationRepository(path)
    for change in ({'expected_revision': 'main-root'}, {'owner': 'foreign'}):
        with pytest.raises(VerificationError):
            repository.reserve(**(intent | change))
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM verification_requests').fetchone() == (0,)


def test_historical_request_stays_pinned_after_later_execution(adopted):
    path, adopted_receipt, intent = adopted
    repository = VerificationRepository(path)
    original = repository.reserve(**intent)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE projects SET active_run_id='run' WHERE id='project'")
    revisions = RevisionRepository(path)
    revisions.reserve('user', intent['workspace_id'], 'run', 'attempt-after-verify',
                      'grant-after-verify', int(time.time()) + 120)
    revisions.bind('user', 'attempt-after-verify', 'broker-after-verify')
    later = revisions.register('user', 'attempt-after-verify', 'broker-after-verify',
                               'grant-after-verify', adopted_receipt.artifact)
    assert later.revision_id != adopted_receipt.revision_id
    assert repository.reserve(**intent) == original
    with pytest.raises(VerificationError, match='verification_conflict'):
        repository.reserve(**(intent | {'request_id': 'new-old-head'}))


def test_late_request_write_failure_leaves_no_evidence(adopted):
    path, _, intent = adopted
    repository = VerificationRepository(path)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TRIGGER deny_v12_verification BEFORE INSERT ON verification_requests "
                   "BEGIN SELECT RAISE(ABORT,'forced'); END")
    with pytest.raises(VerificationError, match='verification_unavailable'):
        repository.reserve(**intent)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM verification_requests').fetchone() == (0,)


def test_schema_drift_after_open_denies_v12_verification(adopted):
    path, _, intent = adopted
    repository = VerificationRepository(path)
    with sqlite3.connect(path) as db:
        db.execute('ALTER TABLE projects ADD COLUMN unexpected TEXT')
    with pytest.raises(VerificationError, match='verification_unavailable'):
        repository.reserve(**intent)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM verification_requests').fetchone() == (0,)


def test_late_report_write_failure_preserves_request(adopted):
    path, _, intent = adopted
    repository = VerificationRepository(path)
    request = repository.reserve(**intent)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TRIGGER deny_v12_report BEFORE INSERT ON verification_results "
                   "BEGIN SELECT RAISE(ABORT,'forced'); END")
    results = [{'key': 'page', 'checkIndex': 0, 'passed': True, 'note': 'observed'}]
    with pytest.raises(VerificationError, match='verification_unavailable'):
        repository.record_report(owner='user', request_id=request.id, results=results)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM verification_requests').fetchone() == (1,)
        assert db.execute('SELECT count(*) FROM verification_results').fetchone() == (0,)
