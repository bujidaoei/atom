"""Offline adoption provenance schema tests; no serving cutover is implied."""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app.migrations import MigrationError, migrate, verify, verify_backup
from app.revisions import RevisionRepository
from app.verification_repository import VerificationError, VerificationRepository
from test_revision_migrations import legacy


def test_v12_requires_verified_v11_source(legacy, tmp_path):
    path, _ = legacy
    backup = tmp_path / 'not-created.db'
    with pytest.raises(MigrationError, match='migration_requires_v11'):
        migrate(path, backup, target_version=12)
    assert not backup.exists() and verify(path) == 0


@pytest.fixture
def populated(legacy, tmp_path):
    path, initial = legacy
    migrate(path, initial, target_version=11)
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        main, = db.execute('SELECT id FROM revision_workspaces WHERE heat_id IS NULL').fetchone()
        heat, = db.execute('SELECT id FROM revision_workspaces WHERE heat_id IS NOT NULL').fetchone()
        for key, revision in [('a'*64, 'b'*64), ('c'*64, 'd'*64)]:
            db.execute('INSERT INTO revision_artifacts VALUES (?,?,14,1)', (key, revision))
        db.execute("INSERT INTO revision_records VALUES ('main-root',?,'project',NULL,?,?,NULL,1)",
                   (main, 'a'*64, 'b'*64))
        db.execute("INSERT INTO revision_records VALUES ('heat-root',?,'project',NULL,?,?,NULL,1)",
                   (heat, 'c'*64, 'd'*64))
        db.execute("INSERT INTO revision_attempts(id,workspace_id,project_id,run_id,generation,base_revision_id,deadline,state,termination_state,outcome,created_at,closed_at) VALUES ('attempt',?,'project','run',1,'main-root',99,'closed','confirmed','succeeded',1,2)", (main,))
        db.execute("INSERT INTO revision_records VALUES ('main-result',?,'project','main-root',?,?,'attempt',2)",
                   (main, 'a'*64, 'b'*64))
        db.execute("INSERT INTO revision_receipts VALUES ('attempt',?,'main-result',?,2)",
                   (main, 'e'*64))
        db.execute("INSERT INTO revision_outbox VALUES ('event',?,'main-result','revision.registered',2,NULL)", (main,))
        db.execute("UPDATE revision_workspaces SET current_revision_id='main-result',generation=2 WHERE id=?", (main,))
        db.execute("UPDATE revision_workspaces SET current_revision_id='heat-root',generation=1 WHERE id=?", (heat,))
        db.execute("UPDATE race_heats SET status='done' WHERE id='heat'")
    return path, main, heat


def test_v12_rebuild_preserves_source_and_backup(populated, tmp_path):
    path, main, heat = populated
    before = tmp_path / 'before-adoption.db'
    result = migrate(path, before, target_version=12)
    assert result.applied and result.version == 12
    assert verify(path) == 12
    assert verify_backup(before, expected_version=11) == result.backup_sha256
    assert not migrate(path, before, target_version=12).applied
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        assert db.execute('SELECT count(*) FROM revision_adoptions').fetchone() == (0,)
        assert db.execute('SELECT id,parent_revision_id,producing_attempt_id,adoption_id FROM revision_records ORDER BY id').fetchall() == [
            ('heat-root', None, None, None), ('main-result', 'main-root', 'attempt', None),
            ('main-root', None, None, None)]
        assert db.execute('SELECT attempt_id,revision_id FROM revision_receipts').fetchall() == [('attempt', 'main-result')]
        assert db.execute('SELECT revision_id FROM revision_outbox').fetchall() == [('main-result',)]
        assert db.execute('SELECT current_revision_id FROM revision_workspaces WHERE id=?', (main,)).fetchone() == ('main-result',)
        assert db.execute('SELECT current_revision_id FROM revision_workspaces WHERE id=?', (heat,)).fetchone() == ('heat-root',)
    with sqlite3.connect(before) as saved:
        assert saved.execute('SELECT id,parent_revision_id,producing_attempt_id FROM revision_records ORDER BY id').fetchall() == [
            ('heat-root', None, None), ('main-result', 'main-root', 'attempt'), ('main-root', None, None)]
    restored = tmp_path / 'restored-v11.db'
    with sqlite3.connect(before) as source, sqlite3.connect(restored) as target:
        source.backup(target)
    assert verify(restored) == 11
    with sqlite3.connect(restored) as db:
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        assert db.execute('SELECT revision_id FROM revision_receipts').fetchone() == ('main-result',)
    assert RevisionRepository(path).current_revision('user', main).revision_id == 'main-result'
    with pytest.raises(VerificationError, match='verification_schema_required'):
        VerificationRepository(path)


def test_adoption_scope_artifact_and_immutability(populated, tmp_path):
    path, main, heat = populated
    migrate(path, tmp_path / 'before-v12.db', target_version=12)
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        insert = '''INSERT INTO revision_adoptions VALUES
            (?,?,?,?,?,?,?,?,?,?)'''
        args = ('adopt','project','heat',heat,'heat-root',main,'main-result','user','f'*64,3)
        for index, replacement in [(1,'foreign'),(2,'unknown'),(3,main),(4,'main-result'),
                                   (5,heat),(6,'main-root'),(7,'unknown')]:
            altered = list(args)
            altered[index] = replacement
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(insert, altered)
        db.execute("UPDATE race_heats SET status='failed' WHERE id='heat'")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(insert, args)
        db.execute("UPDATE race_heats SET status='done' WHERE id='heat'")
        db.execute("UPDATE revision_workspaces SET current_revision_id=NULL WHERE id=?", (heat,))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(insert, args)
        db.execute("UPDATE revision_workspaces SET current_revision_id='heat-root' WHERE id=?", (heat,))
        db.execute(insert, args)
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(insert, args)
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO revision_records(id,workspace_id,project_id,parent_revision_id,artifact_key,snapshot_revision,created_at,adoption_id) VALUES ('bad',?,'project','main-result',?,?,3,'adopt')", (main,'a'*64,'b'*64))
        db.execute("INSERT INTO revision_records(id,workspace_id,project_id,parent_revision_id,artifact_key,snapshot_revision,created_at,adoption_id) VALUES ('adopted',?,'project','main-result',?,?,3,'adopt')", (main,'c'*64,'d'*64))
        db.execute("UPDATE revision_workspaces SET current_revision_id='adopted',generation=3 WHERE id=?", (main,))
        for statement in ("UPDATE revision_adoptions SET actor_id='user'",
                          'DELETE FROM revision_adoptions',
                          "UPDATE revision_records SET created_at=4 WHERE id='adopted'"):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(statement)
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    assert verify(path) == 12


def test_v12_rejects_drift_before_backup(populated, tmp_path):
    path, _, _ = populated
    with sqlite3.connect(path) as db:
        db.execute('ALTER TABLE revision_records ADD COLUMN unplanned TEXT')
    backup = tmp_path / 'blocked.db'
    with pytest.raises(MigrationError, match='unsupported_schema'):
        migrate(path, backup, target_version=12)
    assert not backup.exists()


def test_v12_failed_ddl_and_process_death_restore_v11(populated, tmp_path, monkeypatch):
    import app.migrations as migrations
    from app.migrations import adoption_v12
    path, _, _ = populated
    original = adoption_v12.apply
    def fail(db):
        original(db)
        raise sqlite3.OperationalError('injected after rebuild')
    monkeypatch.setattr(adoption_v12, 'apply', fail)
    backup = tmp_path / 'before-failure.db'
    with pytest.raises(MigrationError, match='migration_failed'):
        migrate(path, backup, target_version=12)
    assert verify(path) == 11 and verify_backup(backup, expected_version=11)
    monkeypatch.setattr(adoption_v12, 'apply', original)
    script = '''import os,sys
from pathlib import Path
from app.migrations import migrate,adoption_v12
original=adoption_v12.apply
def crash(db):
    original(db)
    os._exit(43)
adoption_v12.apply=crash
migrate(Path(sys.argv[1]),Path(sys.argv[2]),target_version=12)
'''
    crash_backup = tmp_path / 'before-crash.db'
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    result = subprocess.run([sys.executable,'-c',script,str(path),str(crash_backup)],
                            env=env,capture_output=True,timeout=30)
    assert result.returncode == 43, result.stderr
    assert verify(path) == 11 and verify_backup(crash_backup, expected_version=11)
    assert migrate(path, tmp_path / 'after-crash.db', target_version=12).applied
