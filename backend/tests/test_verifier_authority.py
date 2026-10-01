"""v13-only verifier credential, evidence and release transaction tests."""
from contextlib import contextmanager
import hashlib
import sqlite3

import pytest

from app.artifacts import Artifact
from app.migrations import migrate, verify
from app.release_repository import ReleaseRepository
from app.verification_contract import capture_report
from app.verification_repository import VerificationError, VerificationRepository
from app.verifier_authority import VerifierAuthority
from test_adoption_repository import Store, prepared, snapshot
from test_adoption_verification_repository import adopted
from test_revision_migrations import legacy


@pytest.fixture
def authorized(adopted, tmp_path):
    path, receipt, intent = adopted
    migrate(path, tmp_path / 'before-v13.db', target_version=13)
    request = VerificationRepository(path).reserve(**intent)
    authority = VerifierAuthority(path)
    assignment = authority.dispatch(owner='user', request_id=request.id,
        artifact=receipt.artifact, route_id='a' * 32, verifier_id='worker-1',
        environment_digest='e' * 64)
    results = [{'key': 'page', 'checkIndex': 0, 'passed': True, 'note': 'observed'}]
    return path, receipt, request, authority, assignment, results


def _register(authority, assignment, results, **changes):
    args = dict(request_id=assignment.request.id, route_id=assignment.route_id,
                verifier_id=assignment.verifier_id,
                environment_digest=assignment.environment_digest,
                artifact=assignment.artifact, credential=assignment.credential,
                results=results)
    return authority.register(**(args | changes))


def _intent(request):
    return dict(owner='user', project_id=request.project_id, release_id='trusted-release',
                verification_id=request.id, expected_revision=request.revision_id,
                expected_generation=0, policy_digest=request.policy_digest,
                runner_version=request.runner_version, audience='public', slug='trusted-site')


def test_dispatch_denies_foreign_owner_wrong_artifact_and_changed_contract(adopted, tmp_path):
    path, receipt, intent = adopted
    migrate(path, tmp_path / 'before-v13.db', target_version=13)
    request = VerificationRepository(path).reserve(**intent)
    authority = VerifierAuthority(path)
    args = dict(owner='user',request_id=request.id,artifact=receipt.artifact,
        route_id='a' * 32,verifier_id='worker-1',environment_digest='e' * 64)
    with pytest.raises(VerificationError, match='verification_not_found'):
        authority.dispatch(**(args | {'owner': 'foreign'}))
    with pytest.raises(VerificationError, match='verification_stale_artifact'):
        authority.dispatch(**(args | {'artifact': Artifact('f' * 64,
            receipt.artifact.revision,receipt.artifact.size)}))
    with sqlite3.connect(path) as db:
        db.execute("UPDATE requirements SET title='Changed' WHERE project_id='project'")
    with pytest.raises(VerificationError, match='verification_stale_contract'):
        authority.dispatch(**args)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM verification_dispatches').fetchone() == (0,)


def test_dispatch_current_derives_artifact_under_owner_and_head_checks(adopted, tmp_path):
    path, receipt, intent = adopted
    migrate(path, tmp_path / 'before-v13.db', target_version=13)
    request = VerificationRepository(path).reserve(**intent)
    authority = VerifierAuthority(path)
    args = dict(request_id=request.id, route_id='a' * 32,
                verifier_id='worker-1', environment_digest='e' * 64)
    with pytest.raises(VerificationError, match='verification_not_found'):
        authority.dispatch_current(owner='foreign', **args)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE revision_workspaces SET current_revision_id=NULL WHERE id=?",
                   (request.workspace_id,))
    with pytest.raises(VerificationError, match='verification_stale_artifact'):
        authority.dispatch_current(owner='user', **args)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE revision_workspaces SET current_revision_id=? WHERE id=?",
                   (request.revision_id, request.workspace_id))
    dispatched = authority.dispatch_current(owner='user', **args)
    assert dispatched.artifact == receipt.artifact
    assert dispatched.request == request
    with pytest.raises(VerificationError, match='verifier_already_dispatched'):
        authority.dispatch_current(owner='user', **args)


def test_single_use_dispatch_and_authentication(authorized):
    path, receipt, request, authority, assignment, results = authorized
    assert len(assignment.credential) == 32
    assert 'credential' not in repr(assignment)
    with sqlite3.connect(path) as db:
        row = db.execute('SELECT credential_digest FROM verification_dispatches').fetchone()
        assert row == (hashlib.sha256(assignment.credential).hexdigest(),)
        assert assignment.credential.hex() not in str(db.execute(
            'SELECT * FROM verification_dispatches').fetchone())
    with pytest.raises(VerificationError, match='verifier_already_dispatched'):
        authority.dispatch(owner='user', request_id=request.id, artifact=receipt.artifact,
            route_id='b' * 32, verifier_id='worker-2', environment_digest='e' * 64)
    for change in ({'credential': b'\0' * 32}, {'credential': b'short'},
                   {'verifier_id': 'worker-2'}, {'environment_digest': 'f' * 64},
                   {'route_id': 'b' * 32},
                   {'artifact': Artifact('f' * 64, receipt.artifact.revision,
                                         receipt.artifact.size)}):
        with pytest.raises(VerificationError, match='verifier_unauthorized'):
            _register(authority, assignment, results, **change)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM verification_results').fetchone() == (0,)
    result = _register(authority, assignment, results)
    assert result.outcome == 'passed'
    with pytest.raises(VerificationError, match='verification_expired'):
        _register(authority, assignment, results)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM verification_results').fetchone() == (1,)
        assert db.execute('SELECT count(*) FROM verification_attestations').fetchone() == (1,)
    assert verify(path) == 13


def test_legacy_report_path_and_unverified_publish_denied(authorized):
    path, receipt, request, authority, assignment, results = authorized
    with pytest.raises(VerificationError, match='verified_registration_required'):
        VerificationRepository(path).record_report(owner='user', request_id=request.id, results=results)
    with pytest.raises(VerificationError, match='verified_release_required'):
        ReleaseRepository(path).publish(**_intent(request))
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM verification_results').fetchone() == (0,)
        assert db.execute('SELECT count(*) FROM release_records').fetchone() == (0,)


def test_authenticated_report_promotes_only_matching_verified_bytes(authorized):
    path, receipt, request, authority, assignment, results = authorized
    report = _register(authority, assignment, results)
    payload, artifact = snapshot(b'<html>heat</html>')
    assert artifact == receipt.artifact
    releases = ReleaseRepository(path)
    with pytest.raises(VerificationError, match='verified_release_required'):
        releases.publish(**_intent(request))
    first = releases.publish_verified(Store(artifact.key, payload), **_intent(request))
    assert first.revision_id == request.revision_id
    assert releases.publish_verified(Store(artifact.key, b'corrupt'), **_intent(request)) == first
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM release_records').fetchone() == (1,)
        assert db.execute('SELECT count(*) FROM content_bindings').fetchone() == (1,)
        assert db.execute('SELECT event_kind FROM security_audit_events').fetchone() == ('release.published',)
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    with sqlite3.connect(path) as db:
        assert hashlib.sha256(report.report).hexdigest() == db.execute(
            'SELECT report_digest FROM verification_attestations').fetchone()[0]
    stopped = releases.unpublish(owner='user', project_id=request.project_id,
        command_id='stop-trusted', expected_release=first.release_id,
        expected_generation=first.generation)
    assert stopped.generation == 2
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT event_kind FROM security_audit_events ORDER BY sequence').fetchall() == [
            ('release.published',), ('release.unpublished',)]
        assert db.execute('SELECT live,generation FROM release_publications').fetchone() == (0,2)


def test_contract_change_during_artifact_preflight_blocks_promotion(authorized):
    path, receipt, request, authority, assignment, results = authorized
    _register(authority, assignment, results)
    payload, artifact = snapshot(b'<html>heat</html>')
    def change_contract():
        with sqlite3.connect(path) as db:
            db.execute("UPDATE requirements SET title='Changed' WHERE project_id='project'")
    with pytest.raises(VerificationError, match='release_stale_evidence'):
        ReleaseRepository(path).publish_verified(Store(artifact.key, payload, hook=change_contract),
                                                 **_intent(request))
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM release_records').fetchone() == (0,)
        assert db.execute('SELECT count(*) FROM release_publications').fetchone() == (0,)
        assert db.execute('SELECT count(*) FROM security_audit_events').fetchone() == (0,)


def test_false_and_forged_digest_cannot_publish(authorized):
    path, receipt, request, authority, assignment, _ = authorized
    failed = [{'key': 'page', 'checkIndex': 0, 'passed': False, 'note': 'missing'}]
    _register(authority, assignment, failed)
    payload, artifact = snapshot(b'<html>heat</html>')
    with pytest.raises(VerificationError, match='release_evidence_required'):
        ReleaseRepository(path).publish_verified(Store(artifact.key, payload), **_intent(request))


@pytest.mark.parametrize('forgery', ['digest', 'result-count'])
def test_forged_digest_fails_final_promotion(adopted, tmp_path, forgery):
    path, receipt, intent = adopted
    migrate(path, tmp_path / 'before-v13.db', target_version=13)
    request = VerificationRepository(path).reserve(**intent)
    assignment = VerifierAuthority(path).dispatch(owner='user', request_id=request.id,
        artifact=receipt.artifact, route_id='a' * 32, verifier_id='worker-1',
        environment_digest='e' * 64)
    report = capture_report(request.contract,
        [{'key': 'page', 'checkIndex': 0, 'passed': forgery == 'digest', 'note': 'observed'}])
    digest = 'f' * 64 if forgery == 'digest' else hashlib.sha256(report.canonical).hexdigest()
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        issued_at, = db.execute('SELECT issued_at FROM verification_dispatches WHERE request_id=?',
                                (request.id,)).fetchone()
        db.execute('''INSERT INTO verification_results VALUES (?,?,?,?,?,?,?,?,?,?)''',
            (request.id,request.workspace_id,request.revision_id,request.contract.digest,
             request.policy_digest,'passed',report.total,1,
             report.canonical.decode(),issued_at))
        db.execute('''INSERT INTO verification_attestations VALUES (?,?,?,?,?,?,?)''',
            (request.id,assignment.verifier_id,assignment.environment_digest,
             receipt.artifact.key,receipt.artifact.revision,digest,issued_at))
    payload, artifact = snapshot(b'<html>heat</html>')
    with pytest.raises(VerificationError, match='release_untrusted_evidence'):
        ReleaseRepository(path).publish_verified(Store(artifact.key, payload), **_intent(request))
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM release_records').fetchone() == (0,)


def test_stale_contract_and_head_reject_registration(authorized):
    path, receipt, request, authority, assignment, results = authorized
    with sqlite3.connect(path) as db:
        db.execute("UPDATE requirements SET title='Changed' WHERE project_id='project'")
    with pytest.raises(VerificationError, match='verification_stale_evidence'):
        _register(authority, assignment, results)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE requirements SET title='Page' WHERE project_id='project'")
        db.execute("UPDATE revision_workspaces SET current_revision_id='main-root' WHERE id=?",
                   (request.workspace_id,))
    with pytest.raises(VerificationError, match='verification_stale_evidence'):
        _register(authority, assignment, results)


def test_expired_credential_and_cross_request_replay(authorized, monkeypatch):
    import app.verifier_authority as module

    path, receipt, request, authority, assignment, results = authorized
    other = VerificationRepository(path).reserve(owner='user', workspace_id=request.workspace_id,
        request_id='other-verification', expected_revision=request.revision_id,
        expected_contract=request.contract.digest, policy_digest=request.policy_digest,
        runner_version=request.runner_version, budget_seconds=60)
    second = authority.dispatch(owner='user', request_id=other.id,
        artifact=receipt.artifact, route_id='b' * 32, verifier_id='worker-1',
        environment_digest='e' * 64)
    with pytest.raises(VerificationError, match='verifier_unauthorized'):
        _register(authority, second, results, credential=assignment.credential)
    monkeypatch.setattr(module.time, 'time', lambda: request.deadline + 1)
    with pytest.raises(VerificationError, match='verification_expired'):
        _register(authority, assignment, results)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM verification_results').fetchone() == (0,)


def test_deadline_crossed_during_report_validation_rolls_back(authorized, monkeypatch):
    import app.verifier_authority as module

    path, receipt, request, authority, assignment, results = authorized
    ticks = iter((request.deadline - 1, request.deadline + 1))
    monkeypatch.setattr(module.time, 'time', lambda: next(ticks))
    with pytest.raises(VerificationError, match='verification_expired'):
        _register(authority, assignment, results)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM verification_results').fetchone() == (0,)
        assert db.execute('SELECT count(*) FROM verification_attestations').fetchone() == (0,)


def test_attestation_write_failure_rolls_back_report(authorized, monkeypatch):
    path, receipt, request, authority, assignment, results = authorized
    original = authority._ledger._transaction
    @contextmanager
    def deny_attestation():
        with original() as db:
            db.set_authorizer(lambda action, table, *rest:
                sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_INSERT
                and table == 'verification_attestations' else sqlite3.SQLITE_OK)
            yield db
    monkeypatch.setattr(authority._ledger, '_transaction', deny_attestation)
    with pytest.raises(VerificationError, match='verification_unavailable'):
        _register(authority, assignment, results)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM verification_results').fetchone() == (0,)
        assert db.execute('SELECT count(*) FROM verification_attestations').fetchone() == (0,)
