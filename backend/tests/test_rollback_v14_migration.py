"""Offline rollback provenance constraints; no public rollback is enabled."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from app.content_bindings import ensure_binding
from app.migrations import MigrationError, migrate, verify, verify_backup
from app.release_repository import ReleaseRepository
from test_adoption_repository import prepared
from test_adoption_verification_repository import adopted
from test_revision_migrations import legacy
from test_v13_content_consumers import published
from test_verifier_authority import authorized


def test_v14_preserves_live_v13_release_and_verified_backup(published, tmp_path):
    path, _store, _intent, first = published
    backup = tmp_path / 'before-v14.db'
    result = migrate(path, backup, target_version=14)
    assert result.version == verify(path) == 14
    assert result.backup_sha256 == verify_backup(backup, expected_version=13)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT release_id,generation,live FROM release_publications').fetchone() == (
            first.release_id, 1, 1)
        assert db.execute('SELECT count(*) FROM release_rollback_sources').fetchone() == (0,)
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    assert migrate(path, backup, target_version=14).applied is False


def test_v14_source_relation_requires_receipt_audit_pointer_and_is_immutable(published, tmp_path):
    path, store, intent, first = published
    second = ReleaseRepository(path).publish_verified(store, **(intent | {
        'release_id':'second-release', 'expected_generation':1}))
    migrate(path, tmp_path / 'before-v14.db', target_version=14)
    new_id, command_id = 'b' * 32, 'c' * 32
    response = {'release_id':new_id, 'source_release_id':first.release_id,
                'displaced_release_id':second.release_id, 'generation':3,
                'slug':intent['slug']}
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('''INSERT INTO release_records
            (id,project_id,workspace_id,revision_id,verification_id,contract_digest,
             policy_digest,audience,creator_id,previous_release_id,created_at)
            SELECT ?,project_id,workspace_id,revision_id,verification_id,contract_digest,
                   policy_digest,audience,creator_id,?,created_at+1
            FROM release_records WHERE id=?''', (new_id, second.release_id, first.release_id))
        binding = ensure_binding(db, project_id='project', release_id=new_id)
        db.execute('UPDATE release_publications SET release_id=?,generation=3 WHERE project_id=?',
                   (new_id, 'project'))
        with pytest.raises(sqlite3.IntegrityError, match='invalid_release_rollback_source'):
            db.execute('INSERT INTO release_rollback_sources VALUES (?,?,?,?,?,?,?)',
                       (new_id, 'project', first.release_id, second.release_id, command_id, 3, 1))
        db.execute('INSERT INTO command_receipts VALUES (?,?,?,?,?)',
                   ('project', 'rollback:' + command_id, 'a' * 64,
                    json.dumps(response, sort_keys=True), '2026-10-02T00:00:00Z'))
        with pytest.raises(sqlite3.IntegrityError, match='invalid_release_rollback_source'):
            db.execute('INSERT INTO release_rollback_sources VALUES (?,?,?,?,?,?,?)',
                       (new_id, 'project', first.release_id, second.release_id, command_id, 3, 1))
        db.execute('''INSERT INTO security_audit_events
            (event_id,schema_version,event_kind,occurred_at,actor_kind,actor_id,
             scope_kind,scope_id,operation_id,binding_id,release_id,revision_id,
             publication_generation)
            VALUES (?,1,'release.published',1,'user','user','project','project',?,?,?,?,3)''',
            ('d' * 32, new_id, binding.id, new_id, first.revision_id))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute('INSERT INTO release_rollback_sources VALUES (?,?,?,?,?,?,?)',
                       (new_id, 'project', second.release_id, second.release_id,
                        command_id, 3, 1))
        db.execute('INSERT INTO release_rollback_sources VALUES (?,?,?,?,?,?,?)',
                   (new_id, 'project', first.release_id, second.release_id, command_id, 3, 1))
        assert db.execute('SELECT source_release_id,displaced_release_id,generation '
                          'FROM release_rollback_sources').fetchone() == (
                              first.release_id, second.release_id, 3)
        with pytest.raises(sqlite3.IntegrityError, match='immutable_release_rollback_source'):
            db.execute('UPDATE release_rollback_sources SET generation=4')
        with pytest.raises(sqlite3.IntegrityError, match='immutable_release_rollback_source'):
            db.execute('DELETE FROM release_rollback_sources')
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_v14_late_ddl_failure_restores_exact_v13(published, tmp_path, monkeypatch):
    from app.migrations import rollback_v14

    path, _store, _intent, first = published
    original = rollback_v14.apply

    def fail(db):
        original(db)
        raise sqlite3.OperationalError('injected after rollback schema creation')

    monkeypatch.setattr(rollback_v14, 'apply', fail)
    backup = tmp_path / 'before-failed-v14.db'
    with pytest.raises(MigrationError, match='migration_failed'):
        migrate(path, backup, target_version=14)
    assert verify(path) == 13
    assert verify_backup(backup, expected_version=13)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT release_id,generation,live FROM release_publications').fetchone() == (
            first.release_id, 1, 1)
        assert db.execute("SELECT 1 FROM sqlite_schema WHERE name='release_rollback_sources'").fetchone() is None


def test_v14_process_death_before_commit_restores_v13(published, tmp_path):
    path, _store, _intent, first = published
    backup = tmp_path / 'before-killed-v14.db'
    script = '''
import os,sys
from pathlib import Path
from app.migrations import migrate,rollback_v14
original=rollback_v14.apply
def die(db):
    original(db)
    os._exit(42)
rollback_v14.apply=die
migrate(Path(sys.argv[1]),Path(sys.argv[2]),target_version=14)
'''
    environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    died = subprocess.run([sys.executable, '-c', script, str(path), str(backup)],
                          env=environment, capture_output=True, timeout=30)
    assert died.returncode == 42, died.stderr
    assert verify(path) == 13
    assert verify_backup(backup, expected_version=13)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT release_id,generation,live FROM release_publications').fetchone() == (
            first.release_id, 1, 1)
        assert db.execute("SELECT 1 FROM sqlite_schema WHERE name='release_rollback_sources'").fetchone() is None
