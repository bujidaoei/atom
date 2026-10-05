"""Real SQLite migration and policy constraints; no publication serving claim."""
import sqlite3
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.migrations import MigrationError, migrate, verify, verify_backup
from app.release_repository import ReleaseRepository
from app.artifacts import ArtifactError
from app.verification_repository import VerificationError
from test_adoption_repository import prepared
from test_adoption_verification_repository import adopted
from test_revision_migrations import legacy
from test_v13_content_consumers import published
from test_verifier_authority import authorized
from test_rollback_v14_repository import historical, _rollback_intent


@pytest.fixture
def v15_history(historical, tmp_path):
    path, store, intent, source, displaced = historical
    ReleaseRepository(path).rollback_verified(store, **_rollback_intent(intent, source, displaced))
    migrate(path, tmp_path / 'before-v15.db', target_version=15)
    return path


def test_v16_preserves_records_bindings_receipts_and_restore_provenance(v15_history, tmp_path):
    path = v15_history
    preserved = ('release_records', 'release_publications', 'content_bindings',
                 'release_rollback_sources', 'command_receipts', 'security_audit_events')
    with sqlite3.connect(path) as db:
        originals = {table: db.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall() for table in preserved}
    backup = tmp_path / 'before-v16.db'
    receipt = migrate(path, backup, target_version=16)
    assert receipt.version == verify(path) == 16
    assert receipt.backup_sha256 == verify_backup(backup, expected_version=15)
    with sqlite3.connect(path) as db:
        for table in preserved:
            rows = db.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall()
            if table == 'release_records':
                assert all(row[-2] == 'required' for row in rows)
                rows = [row[:-2] for row in rows]
            assert rows == originals[table]
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    assert not migrate(path, backup, target_version=16).applied


def test_v16_advisory_needs_real_revision_and_required_needs_evidence(v15_history, tmp_path):
    path = v15_history
    migrate(path, tmp_path / 'before-policy.db', target_version=16)
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        row = db.execute('SELECT project_id,workspace_id,revision_id,creator_id FROM release_records LIMIT 1').fetchone()
        project, workspace, revision, owner = row
        insert = '''INSERT INTO release_records
            (id,project_id,workspace_id,revision_id,creator_id,created_at,audience,verification_mode,publication_generation)
            VALUES (?,?,?,?,?,1,'public',?,4)'''
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(insert, ('required-missing', project, workspace, revision, owner, 'required'))
        for bad in [('wrong-revision', project, workspace, 'absent', owner, 'advisory'),
                    ('wrong-owner', project, workspace, revision, 'foreign', 'advisory'),
                    ('wrong-project', 'foreign', workspace, revision, owner, 'advisory')]:
            with pytest.raises(sqlite3.IntegrityError, match='invalid_release_(revision_scope|generation)'):
                db.execute(insert, bad)
        db.execute(insert, ('advisory-ok', project, workspace, revision, owner, 'advisory'))
        assert db.execute("SELECT verification_id,contract_digest,policy_digest FROM release_records WHERE id='advisory-ok'").fetchone() == (None, None, None)
        with pytest.raises(sqlite3.IntegrityError, match='immutable_release_evidence'):
            db.execute("UPDATE release_records SET verification_mode='required' WHERE id='advisory-ok'")
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_v16_failed_rebuild_restores_exact_v15(v15_history, tmp_path, monkeypatch):
    from app.migrations import publication_policy_v16
    apply = publication_policy_v16.apply

    def fail(db):
        apply(db)
        raise sqlite3.OperationalError('injected before commit')

    monkeypatch.setattr(publication_policy_v16, 'apply', fail)
    backup = tmp_path / 'failed-v16.db'
    with pytest.raises(MigrationError, match='migration_failed'):
        migrate(v15_history, backup, target_version=16)
    assert verify(v15_history) == 15
    assert verify_backup(backup, expected_version=15)


def test_v16_process_death_before_commit_preserves_live_history(v15_history, tmp_path):
    path = v15_history
    with sqlite3.connect(path) as db:
        before = db.execute('SELECT * FROM release_publications').fetchall()
    backup = tmp_path / 'killed-v16.db'
    script = '''
import os, sys
from pathlib import Path
from app.migrations import migrate, publication_policy_v16
original = publication_policy_v16.apply
def die(db):
    original(db)
    os._exit(42)
publication_policy_v16.apply = die
migrate(Path(sys.argv[1]), Path(sys.argv[2]), target_version=16)
'''
    result = subprocess.run([sys.executable, '-c', script, str(path), str(backup)],
        env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1])),
        capture_output=True, timeout=30)
    assert result.returncode == 42, result.stderr
    assert verify(path) == 15
    assert verify_backup(backup, expected_version=15)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT * FROM release_publications').fetchall() == before
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_advisory_publication_ignores_contract_quality_but_preserves_exact_artifact(v15_history, historical, tmp_path):
    path, store, intent, _source, _displaced = historical
    migrate(path, tmp_path / 'direct-v16.db', target_version=16)
    repository = ReleaseRepository(path, required_schema=16)
    args = {key: value for key, value in intent.items()
            if key not in ('verification_id', 'policy_digest', 'runner_version')}
    args.update(release_id='a' * 32, expected_generation=3)
    # Broken optional contract cannot disable delivery of a valid saved page.
    with sqlite3.connect(path) as db:
        db.execute("UPDATE requirements SET checks_json='not valid json'")
    receipt = repository.publish_snapshot(store, **args)
    assert receipt.generation == 4
    current = repository.current(owner='user', project_id='project')
    assert current.verification_id is None and current.verification_mode == 'advisory'
    published_artifact = repository.resolve(slug=receipt.slug)
    assert published_artifact.revision_id == args['expected_revision']
    assert repository.publish_snapshot(store, **args) == receipt
    with pytest.raises(VerificationError, match='release_conflict'):
        repository.publish_snapshot(store, **(args | {'release_id': 'b' * 32}))
    with pytest.raises(VerificationError, match='release_not_found'):
        repository.publish_snapshot(store, **(args | {'owner': 'foreign'}))
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM security_audit_events WHERE release_id=?',
                          (receipt.release_id,)).fetchone() == (1,)
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_advisory_corrupt_storage_preserves_previous_live_version(v15_history, historical, tmp_path, monkeypatch):
    path, store, intent, _source, _displaced = historical
    migrate(path, tmp_path / 'corruption-v16.db', target_version=16)
    repository = ReleaseRepository(path, required_schema=16)
    before = repository.current(owner='user', project_id='project')
    args = {key: value for key, value in intent.items()
            if key not in ('verification_id', 'policy_digest', 'runner_version')}
    args.update(release_id='a' * 32, expected_generation=3)
    monkeypatch.setattr(store, 'read', lambda _key: b'corrupt snapshot')
    with pytest.raises(ArtifactError, match='release_artifact_mismatch'):
        repository.publish_snapshot(store, **args)
    assert repository.current(owner='user', project_id='project') == before


def test_advisory_restore_after_unpublish_preserves_draft_and_history(v15_history, historical, tmp_path):
    path, store, intent, _source, _displaced = historical
    migrate(path, tmp_path / 'restore-v16.db', target_version=16)
    repository = ReleaseRepository(path, required_schema=16)
    args = {key: value for key, value in intent.items()
            if key not in ('verification_id', 'policy_digest', 'runner_version')}
    args.update(release_id='a' * 32, expected_generation=3)
    published = repository.publish_snapshot(store, **args)
    repository.unpublish(owner='user', project_id='project', command_id='b' * 32,
        expected_release=published.release_id, expected_generation=4)
    with sqlite3.connect(path) as db:
        before = db.execute('SELECT current_revision_id,generation FROM revision_workspaces WHERE heat_id IS NULL').fetchone()
        db.execute("UPDATE projects SET status='failed' WHERE id='project'")
    restore = dict(owner='user', project_id='project', command_id='1' * 32,
        release_id='2' * 32, source_release_id=published.release_id,
        expected_release=published.release_id, expected_generation=5,
        expected_revision=intent['expected_revision'])
    result = repository.restore_snapshot(store, **restore)
    assert result.generation == 6
    assert repository.restore_snapshot(store, **restore) == result
    current = repository.current(owner='user', project_id='project')
    assert current.live and current.verification_mode == 'advisory'
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT current_revision_id,generation FROM revision_workspaces WHERE heat_id IS NULL').fetchone() == before
        assert db.execute('SELECT source_release_id,displaced_release_id FROM release_rollback_sources WHERE new_release_id=?',
                          (result.release_id,)).fetchone() == (published.release_id, published.release_id)
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    with pytest.raises(VerificationError, match='release_conflict'):
        repository.restore_snapshot(store, **(restore | {'release_id': 'e' * 32, 'command_id': 'f' * 32}))


def test_history_uses_committed_order_across_equal_and_backward_clocks(v15_history, historical, tmp_path, monkeypatch):
    import time
    from app.release_history import publication_history
    path, store, intent, _, _ = historical
    migrate(path, tmp_path / 'ordered-v16.db', target_version=16)
    repository = ReleaseRepository(path, required_schema=16)
    args = {key: value for key, value in intent.items()
            if key not in ('verification_id', 'policy_digest', 'runner_version')}
    now = int(time.time())
    for generation, identity, timestamp in ((3, 'f', now), (4, 'e', now), (5, '0', now - 10)):
        monkeypatch.setattr('app.release_repository.time.time', lambda timestamp=timestamp: timestamp)
        repository.publish_snapshot(store, **(args | {'release_id': identity * 32, 'expected_generation': generation}))
    first = publication_history(path, owner='user', project_id='project', limit=1)
    assert first['items'][0]['releaseId'] == '0' * 32 and first['items'][0]['version'] == 6
    # A later insertion must not move the continuation window or repeat rows.
    repository.publish_snapshot(store, **(args | {'release_id': '1' * 32, 'expected_generation': 6}))
    versions = [6]
    cursor = first['nextCursor']
    while cursor:
        page = publication_history(path, owner='user', project_id='project', limit=1, cursor=cursor)
        versions.extend(item['version'] for item in page['items'])
        cursor = page['nextCursor']
    assert versions == [6, 5, 4, 3, 2, 1]
    assert publication_history(path, owner='user', project_id='project')['items'][0]['version'] == 7
    for cursor in ('0', '-1', '01', str(2**63), '1:old'):
        with pytest.raises(VerificationError, match='invalid_release_request'):
            publication_history(path, owner='user', project_id='project', cursor=cursor)


def test_generation_backfill_refuses_missing_historical_receipt(v15_history, tmp_path):
    with sqlite3.connect(v15_history) as db:
        db.execute("DELETE FROM command_receipts WHERE key LIKE 'release:%'")
    assert verify(v15_history) == 15
    backup = tmp_path / 'missing-receipt-v16.db'
    with pytest.raises(MigrationError, match='migration_failed'):
        migrate(v15_history, backup, target_version=16)
    assert verify(v15_history) == 15
    assert verify_backup(backup, expected_version=15)


def test_operator_cli_migrates_exact_predecessor_with_verified_backup(v15_history, tmp_path):
    import json
    backup = tmp_path / 'operator-before-16.db'
    result = subprocess.run([sys.executable, '-m', 'app.migrations', str(v15_history),
        '--backup', str(backup), '--target-version', '16'],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt['version'] == verify(v15_history) == 16
    assert receipt['backup_sha256'] == verify_backup(backup, expected_version=15)


def test_concurrent_restore_has_one_committed_generation(v15_history, historical, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.release_history import publication_history
    path, store, intent, source, _ = historical
    migrate(path, tmp_path / 'concurrent-v16.db', target_version=16)
    repository = ReleaseRepository(path, required_schema=16)
    before = repository.current(owner='user', project_id='project')
    barrier = Barrier(2)

    def restore(identity):
        barrier.wait(timeout=5)
        try:
            return repository.restore_snapshot(store, owner='user', project_id='project',
                command_id=identity * 32, release_id=identity * 32,
                source_release_id=source.release_id, expected_release=before.release_id,
                expected_generation=before.generation, expected_revision=intent['expected_revision'])
        except VerificationError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(restore, ('a', 'b')))
    assert results.count('release_conflict') == 1
    winner = next(result for result in results if not isinstance(result, str))
    current = repository.current(owner='user', project_id='project')
    assert current.release_id == winner.release_id and current.generation == before.generation + 1
    history = publication_history(path, owner='user', project_id='project')
    assert [item['version'] for item in history['items']] == [4, 3, 2, 1]
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        assert db.execute("SELECT count(*) FROM security_audit_events WHERE event_kind='release.published' AND publication_generation=4").fetchone() == (1,)
