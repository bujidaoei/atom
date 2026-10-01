"""Offline verifier provenance upgrade and fail-closed release constraints."""
import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app.migrations import MigrationError, migrate, verify, verify_backup
from app.verification_repository import VerificationRepository
from test_adoption_repository import prepared
from test_adoption_verification_repository import adopted
from test_adoption_release_repository import publication
from test_revision_migrations import legacy


def _dispatch(db, request, receipt, **changes):
    values = dict(request_id=request.id, project_id=request.project_id,
                  workspace_id=request.workspace_id, revision_id=request.revision_id,
                  contract_digest=request.contract.digest, policy_digest=request.policy_digest,
                  runner_version=request.runner_version, artifact_key=receipt.artifact.key,
                  snapshot_revision=receipt.artifact.revision,
                  artifact_size=receipt.artifact.size, route_id='a' * 32,
                  verifier_id='worker-1', environment_digest='e' * 64,
                  credential_digest='f' * 64, issued_at=request.created_at,
                  deadline=request.deadline)
    values.update(changes)
    names = ','.join(values)
    db.execute(f'INSERT INTO verification_dispatches ({names}) VALUES ({",".join("?" for _ in values)})',
               tuple(values.values()))


def _attest(db, request, receipt, result, **changes):
    values = dict(request_id=request.id, verifier_id='worker-1',
                  environment_digest='e' * 64, artifact_key=receipt.artifact.key,
                  snapshot_revision=receipt.artifact.revision,
                  report_digest=hashlib.sha256(result.report).hexdigest(),
                  observed_at=result.completed_at)
    values.update(changes)
    names = ','.join(values)
    db.execute(f'INSERT INTO verification_attestations ({names}) VALUES ({",".join("?" for _ in values)})',
               tuple(values.values()))


def _release(db, request, **changes):
    values = dict(id='release-v13', project_id=request.project_id,
                  workspace_id=request.workspace_id, revision_id=request.revision_id,
                  verification_id=request.id, contract_digest=request.contract.digest,
                  policy_digest=request.policy_digest, audience='owner', creator_id='user',
                  previous_release_id=None, created_at=request.created_at)
    values.update(changes)
    names = ','.join(values)
    db.execute(f'INSERT INTO release_records ({names}) VALUES ({",".join("?" for _ in values)})',
               tuple(values.values()))


def test_requires_exact_v12(legacy, tmp_path):
    path, _ = legacy
    backup = tmp_path / 'none.db'
    with pytest.raises(MigrationError, match='migration_requires_v12'):
        migrate(path, backup, target_version=13)
    assert verify(path) == 0 and not backup.exists()


def test_upgrade_preserves_untrusted_history(adopted, tmp_path):
    path, receipt, intent = adopted
    repository = VerificationRepository(path)
    request = repository.reserve(**intent)
    repository.record_report(owner='user', request_id=request.id,
        results=[{'key': 'page', 'checkIndex': 0, 'passed': True, 'note': 'observed'}])
    backup = tmp_path / 'v12.db'
    upgraded = migrate(path, backup, target_version=13)
    assert upgraded.applied and upgraded.version == 13
    assert verify_backup(backup, expected_version=12) == upgraded.backup_sha256
    assert verify(path) == 13 and not migrate(path, backup, target_version=13).applied
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        assert db.execute('SELECT count(*) FROM verification_results').fetchone() == (1,)
        assert db.execute('SELECT count(*) FROM verification_dispatches').fetchone() == (0,)
        assert db.execute('SELECT count(*) FROM verification_attestations').fetchone() == (0,)
        with pytest.raises(sqlite3.IntegrityError, match='release_requires_trusted_verification'):
            _release(db, request)
        with pytest.raises(sqlite3.IntegrityError, match='invalid_verification_dispatch'):
            _dispatch(db, request, receipt)
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    assert verify(path) == 13


def test_new_dispatch_attestation_and_release_constraints(adopted, tmp_path):
    path, receipt, intent = adopted
    request = VerificationRepository(path).reserve(**intent)
    migrate(path, tmp_path / 'pre-v13.db', target_version=13)
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        with pytest.raises(sqlite3.IntegrityError, match='release_requires_trusted_verification'):
            _release(db, request)
        for change in ({'project_id': 'foreign'}, {'revision_id': 'main-root'},
                       {'artifact_key': 'b' * 64}, {'artifact_size': 14},
                       {'runner_version': 'other'}, {'deadline': request.deadline + 1}):
            with pytest.raises(sqlite3.IntegrityError):
                _dispatch(db, request, receipt, **change)
        _dispatch(db, request, receipt)
        with pytest.raises(sqlite3.IntegrityError):
            _dispatch(db, request, receipt)
        for statement in ("UPDATE verification_dispatches SET verifier_id='worker-2'",
                          'DELETE FROM verification_dispatches',
                          "REPLACE INTO verification_dispatches SELECT * FROM verification_dispatches"):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(statement)
        report = b'{"results":[{"key":"page","checkIndex":0,"passed":true,"note":"observed"}]}'
        observed_at = request.created_at + 1
        db.execute('INSERT INTO verification_results VALUES (?,?,?,?,?,?,?,?,?,?)',
                   (request.id, request.workspace_id, request.revision_id,
                    request.contract.digest, request.policy_digest, 'passed', 1, 1,
                    report.decode(), observed_at))
        result = SimpleNamespace(report=report, completed_at=observed_at)
        for change in ({'verifier_id': 'worker-2'}, {'artifact_key': 'b' * 64},
                       {'observed_at': request.deadline + 1}):
            with pytest.raises(sqlite3.IntegrityError):
                _attest(db, request, receipt, result, **change)
        _attest(db, request, receipt, result)
        with pytest.raises(sqlite3.IntegrityError):
            _attest(db, request, receipt, result)
        for statement in ("UPDATE verification_attestations SET verifier_id='worker-2'",
                          'DELETE FROM verification_attestations',
                          'REPLACE INTO verification_attestations SELECT * FROM verification_attestations'):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(statement)
        _release(db, request)
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    assert verify(path) == 13


def test_live_untrusted_release_blocks_upgrade(publication, tmp_path):
    path, releases, _, store, intent = publication
    releases.publish_verified(store, **intent)
    backup = tmp_path / 'pre-v13.db'
    with pytest.raises(MigrationError, match='live_untrusted_release'):
        migrate(path, backup, target_version=13)
    assert verify(path) == 12
    assert verify_backup(backup, expected_version=12)


def test_drift_blocks_upgrade_before_backup(adopted, tmp_path):
    path, _, _ = adopted
    with sqlite3.connect(path) as db:
        db.execute('ALTER TABLE projects ADD COLUMN drift TEXT')
    no_backup = tmp_path / 'drift.db'
    with pytest.raises(MigrationError, match='unsupported_schema'):
        migrate(path, no_backup, target_version=13)
    assert not no_backup.exists()


def test_crash_rolls_back_and_backup_restores_v12(adopted, tmp_path, monkeypatch):
    from app.migrations import verifier_v13

    path, _, _ = adopted
    original = verifier_v13.apply
    def fail(db):
        original(db)
        raise sqlite3.OperationalError('injected after v13 DDL')
    monkeypatch.setattr(verifier_v13, 'apply', fail)
    backup = tmp_path / 'failure.db'
    with pytest.raises(MigrationError, match='migration_failed'):
        migrate(path, backup, target_version=13)
    assert verify(path) == 12 and verify_backup(backup, expected_version=12)
    monkeypatch.setattr(verifier_v13, 'apply', original)
    script = '''import os,sys
from pathlib import Path
from app.migrations import migrate,verifier_v13
original=verifier_v13.apply
def crash(db):
    original(db)
    os._exit(43)
verifier_v13.apply=crash
migrate(Path(sys.argv[1]),Path(sys.argv[2]),target_version=13)
'''
    crash_backup = tmp_path / 'crash.db'
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    completed = subprocess.run([sys.executable, '-c', script, str(path), str(crash_backup)],
                               env=env, capture_output=True, timeout=30)
    assert completed.returncode == 43, completed.stderr
    assert verify(path) == 12 and verify_backup(crash_backup, expected_version=12)
    assert migrate(path, tmp_path / 'retry.db', target_version=13).applied
