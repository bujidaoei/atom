from pathlib import Path
import sqlite3
import os
import subprocess
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, User, Project, Run, Race, RaceHeat
from app.migrations import MigrationError, migrate, verify, verify_backup, backup_database
import app.migrations as migrations


@pytest.fixture
def legacy(tmp_path):
    path = tmp_path / "api.db"
    engine = create_engine("sqlite:///" + path.as_posix())
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(User(id="user", email="user@example.invalid", name="User", password_hash="synthetic", credits=10))
        session.flush()
        session.add(Project(id="project", user_id="user", prompt="actual preserved input", title="Project"))
        session.flush()
        session.add(Run(id="run", project_id="project", role="alex", model="test"))
        session.add(Race(id="race", project_id="project"))
        session.flush()
        session.add(RaceHeat(id="heat", race_id="race", model="test"))
        session.commit()
    engine.dispose()
    return path, tmp_path / "backup.db"


def test_migrate_backup_preserves_legacy_and_creates_only_empty_heads(legacy):
    path, backup = legacy
    result = migrate(path, backup)
    assert result.version == 1 and result.applied and verify(path) == 1
    assert verify_backup(backup) == result.backup_sha256
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT prompt FROM projects").fetchone()[0] == "actual preserved input"
        rows = db.execute("SELECT project_id,heat_id,current_revision_id,generation,active_attempt_id FROM revision_workspaces ORDER BY heat_id").fetchall()
        assert rows == [("project", None, None, 0, None), ("project", "heat", None, 0, None)]
        assert db.execute("SELECT COUNT(*) FROM revision_records").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM revision_attempts").fetchone()[0] == 0
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
    with sqlite3.connect(backup) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
        assert not db.execute("SELECT 1 FROM sqlite_schema WHERE name='revision_workspaces'").fetchall()
    assert not migrate(path, backup).applied


def test_failed_ddl_rolls_back_but_preserves_verified_backup(legacy, monkeypatch):
    path, backup = legacy
    original = migrations._apply_revision_schema
    def fail(db):
        original(db)
        raise sqlite3.OperationalError("synthetic ddl failure")
    monkeypatch.setattr(migrations, "_apply_revision_schema", fail)
    with pytest.raises(MigrationError):
        migrate(path, backup)
    assert verify(path) == 0
    assert verify_backup(backup)
    with sqlite3.connect(path) as db:
        assert not db.execute("SELECT 1 FROM sqlite_schema WHERE name='revision_workspaces'").fetchall()
        assert db.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1


@pytest.mark.parametrize("change", ["PRAGMA user_version=9", "ALTER TABLE projects ADD COLUMN unexplained TEXT"])
def test_unknown_or_drifted_schema_has_no_migration_effects(legacy, change):
    path, backup = legacy
    with sqlite3.connect(path) as db:
        db.execute(change)
    with pytest.raises(MigrationError, match="unsupported_schema"):
        migrate(path, backup)
    assert not backup.exists()


def test_existing_backup_and_source_alias_never_overwrite(legacy):
    path, backup = legacy
    backup.write_bytes(b"canary")
    with pytest.raises(MigrationError):
        migrate(path, backup)
    assert backup.read_bytes() == b"canary" and verify(path) == 0
    with pytest.raises(MigrationError):
        migrate(path, path)
    assert verify(path) == 0


def test_busy_writer_fails_without_backup(legacy):
    path, backup = legacy
    with sqlite3.connect(path) as writer:
        writer.execute("BEGIN IMMEDIATE")
        with pytest.raises(MigrationError):
            migrate(path, backup, lock_timeout=0.05)
        writer.rollback()
    assert not backup.exists() and verify(path) == 0


def test_backup_restores_into_new_database(legacy, tmp_path):
    path, backup = legacy
    migrate(path, backup)
    restored = tmp_path / "restored.db"
    with sqlite3.connect(backup) as source, sqlite3.connect(restored) as target:
        source.backup(target)
    assert verify(restored) == 0
    with sqlite3.connect(restored) as db:
        assert db.execute("SELECT prompt FROM projects").fetchone()[0] == "actual preserved input"
    assert migrate(restored, tmp_path / "restored-backup.db").applied


def test_wal_backup_includes_committed_uncheckpointed_rows(legacy):
    path, backup = legacy
    with sqlite3.connect(path) as writer:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("UPDATE projects SET prompt='committed WAL input'")
        writer.commit()
        assert Path(str(path) + "-wal").stat().st_size > 0
        migrate(path, backup)
        with sqlite3.connect(backup) as restored:
            assert restored.execute("SELECT prompt FROM projects").fetchone() == ("committed WAL input",)
            assert restored.execute("PRAGMA journal_mode").fetchone() == ("delete",)


def test_process_death_during_ddl_rolls_back_on_reopen(legacy, tmp_path):
    path, backup = legacy
    script = '''
import os, sys
from pathlib import Path
import app.migrations as m
original = m._apply_revision_schema
def crash(db):
    original(db)
    os._exit(41)
m._apply_revision_schema = crash
m.migrate(Path(sys.argv[1]), Path(sys.argv[2]))
'''
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    result = subprocess.run([sys.executable, "-c", script, str(path), str(backup)], env=env,
                            capture_output=True, timeout=30)
    assert result.returncode == 41, result.stderr
    assert verify(path) == 0 and verify_backup(backup)
    assert migrate(path, tmp_path / "after-crash.db").applied


def test_constraints_reject_scope_confusion_and_mutable_evidence(legacy):
    path, backup = legacy
    migrate(path, backup)
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA foreign_keys=ON")
        main, = db.execute("SELECT id FROM revision_workspaces WHERE heat_id IS NULL").fetchone()
        heat, = db.execute("SELECT id FROM revision_workspaces WHERE heat_id IS NOT NULL").fetchone()
        db.execute("INSERT INTO revision_artifacts VALUES (?,?,14,1)", ("a"*64, "b"*64))
        db.execute("INSERT INTO revision_records VALUES ('root',?,'project',NULL,?,?,NULL,1)", (main,"a"*64,"b"*64))
        db.execute("INSERT INTO revision_records VALUES ('heat-root',?,'project',NULL,?,?,NULL,1)", (heat,"a"*64,"b"*64))
        attempt = "INSERT INTO revision_attempts(id,workspace_id,project_id,run_id,generation,base_revision_id,deadline,state,termination_state,created_at) VALUES (?,?,'project','run',? ,?,99,'active','pending',1)"
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(attempt, ('wrong-heat',heat,1,'heat-root'))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(attempt, ('wrong-base',main,1,'heat-root'))
        db.execute(attempt, ('attempt',main,1,'root'))
        db.execute("INSERT INTO revision_records VALUES ('result',?,'project','root',?,?,'attempt',1)", (main,'a'*64,'b'*64))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO revision_receipts VALUES ('attempt',?,'root',?,1)", (main,'c'*64))
        db.execute("INSERT INTO revision_receipts VALUES ('attempt',?,'result',?,1)", (main,'c'*64))
        for statement in (
            "UPDATE revision_records SET created_at=2",
            "DELETE FROM revision_artifacts",
            "UPDATE revision_receipts SET created_at=2",
            "UPDATE revision_attempts SET state='closed'",
            "UPDATE runs SET heat_id='heat'",
            "INSERT INTO revision_artifacts VALUES (NULL,'" + 'b'*64 + "',14,1)",
            "UPDATE atom_schema_migrations SET backup_sha256='invalid'",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(statement)
        db.commit()
        db.execute("UPDATE revision_workspaces SET current_revision_id='heat-root' WHERE id=?", (main,))
        with pytest.raises(sqlite3.IntegrityError):
            db.commit()
        db.rollback()
        assert not db.execute("PRAGMA foreign_key_check").fetchall()


def test_schema_identity_preserves_sql_literal_case(legacy):
    path, backup = legacy
    migrate(path, backup)
    with sqlite3.connect(path) as db:
        name = 'revision_records_no_update'
        sql = db.execute("SELECT sql FROM sqlite_schema WHERE name=?", (name,)).fetchone()[0]
        db.execute('DROP TRIGGER ' + name)
        db.execute(sql.replace('immutable_revision_evidence', 'IMMUTABLE_REVISION_EVIDENCE'))
    with pytest.raises(MigrationError, match='unsupported_schema'):
        verify(path)


@pytest.mark.parametrize('version', [0, 1])
def test_supported_backup_wal_restore_and_no_overwrite(legacy, tmp_path, version):
    path, baseline_backup = legacy
    if version:
        migrate(path, baseline_backup)
    destination = tmp_path / 'version-backup.db'
    with sqlite3.connect(path) as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute("UPDATE projects SET prompt='saved committed WAL revision'")
        writer.commit()
        result = backup_database(path, destination)
        assert result.version == version
        assert result.sha256 == verify_backup(destination, expected_version=version)
        assert verify(path) == version
        before = destination.read_bytes()
        with pytest.raises(MigrationError):
            backup_database(path, destination)
        assert destination.read_bytes() == before
    restored = tmp_path / 'version-restored.db'
    with sqlite3.connect(destination) as source, sqlite3.connect(restored) as target:
        source.backup(target)
    assert verify(restored) == version
    with sqlite3.connect(restored) as db:
        assert db.execute('SELECT prompt FROM projects').fetchone() == ('saved committed WAL revision',)
        if version:
            assert db.execute('SELECT count(*) FROM revision_workspaces').fetchone() == (2,)
            assert db.execute('SELECT count(*) FROM atom_schema_migrations').fetchone() == (1,)
    with pytest.raises(MigrationError, match='invalid_backup_version'):
        verify_backup(destination, expected_version=1-version)


def test_versioned_backup_denies_busy_writer_and_drift(legacy, tmp_path):
    path, baseline = legacy
    migrate(path, baseline)
    destination = tmp_path / 'denied.db'
    with sqlite3.connect(path) as writer:
        writer.execute('BEGIN IMMEDIATE')
        with pytest.raises(MigrationError):
            backup_database(path, destination, lock_timeout=0.05)
        assert not destination.exists()
        writer.rollback()
        writer.execute('ALTER TABLE projects ADD COLUMN drift TEXT')
    with pytest.raises(MigrationError, match='unsupported_schema'):
        backup_database(path, destination)
    assert not destination.exists()


@pytest.mark.parametrize('version', [True, None, -1, 3, '1'])
def test_backup_expected_version_is_explicit(legacy, version):
    with pytest.raises(MigrationError, match='invalid_backup_version'):
        verify_backup(legacy[0], expected_version=version)


@pytest.mark.parametrize('source_version', [0, 1])
def test_release_migration_preserves_backup_and_journal(legacy, tmp_path, source_version):
    path, baseline = legacy
    if source_version:
        migrate(path, baseline)
    backup = tmp_path / 'before-release.db'
    result = migrate(path, backup, target_version=2)
    assert result.version == 2 and verify(path) == 2
    assert result.backup_sha256 == verify_backup(backup, expected_version=source_version)
    assert not migrate(path, backup, target_version=2).applied
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT version FROM atom_schema_migrations ORDER BY version').fetchall() == [(1,), (2,)]
        assert db.execute('SELECT prompt FROM projects').fetchone() == ('actual preserved input',)
        assert db.execute('SELECT count(*) FROM verification_requests').fetchone() == (0,)
        assert db.execute('SELECT count(*) FROM release_records').fetchone() == (0,)
    with pytest.raises(MigrationError, match='migration_downgrade_denied'):
        migrate(path, tmp_path / 'downgrade.db')
    assert not (tmp_path / 'downgrade.db').exists()
    restored = tmp_path / 'restore-release.db'
    with sqlite3.connect(backup) as src, sqlite3.connect(restored) as dst:
        src.backup(dst)
    assert verify(restored) == source_version


def test_release_migration_failure_restores_v1_journal(legacy, tmp_path, monkeypatch):
    from app.migrations import release_v2
    path, baseline = legacy
    migrate(path, baseline)
    original = release_v2.apply
    def fail(db):
        original(db)
        raise sqlite3.OperationalError('injected after journal rebuild')
    monkeypatch.setattr(release_v2, 'apply', fail)
    backup = tmp_path / 'before-v2.db'
    with pytest.raises(MigrationError):
        migrate(path, backup, target_version=2)
    assert verify(path) == 1 and verify_backup(backup, expected_version=1)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT version FROM atom_schema_migrations').fetchall() == [(1,)]


def test_release_evidence_scopes_and_immutability(legacy):
    path, backup = legacy
    migrate(path, backup, target_version=2)
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        main, = db.execute('SELECT id FROM revision_workspaces WHERE heat_id IS NULL').fetchone()
        heat, = db.execute('SELECT id FROM revision_workspaces WHERE heat_id IS NOT NULL').fetchone()
        # Schema fixtures only; these descriptors are not real accepted artifacts.
        db.execute('INSERT INTO revision_artifacts VALUES (?,?,14,1)', ('a'*64, 'b'*64))
        for name, workspace in [('root', main), ('heat-root', heat)]:
            db.execute("INSERT INTO revision_records VALUES (?,?,'project',NULL,?,?,NULL,1)", (name, workspace, 'a'*64, 'b'*64))
        request = "INSERT INTO verification_requests VALUES (?,?,?,? ,?,'[]',?,'runner-v1','user',10,20)"
        args = ('check',main,'project','root','c'*64,'d'*64)
        for invalid in [('foreign',main,'unknown','root','c'*64,'d'*64),
                        ('wrong-root',main,'project','heat-root','c'*64,'d'*64)]:
            with pytest.raises(sqlite3.IntegrityError): db.execute(request, invalid)
        db.execute(request, args)
        result = "INSERT INTO verification_results VALUES ('check',? ,?,?,? ,?,1,?,'[]',?)"
        for values in [(main,'heat-root','c'*64,'d'*64,'passed',1,15),
                       (main,'root','e'*64,'d'*64,'passed',1,15),
                       (main,'root','c'*64,'d'*64,'passed',0,15),
                       (main,'root','c'*64,'d'*64,'passed',1,21)]:
            with pytest.raises(sqlite3.IntegrityError): db.execute(result, values)
        db.execute(result, (main,'root','c'*64,'d'*64,'passed',1,15))
        release = "INSERT INTO release_records VALUES (?,? ,?,'root','check',?,?,'owner','user',NULL,16)"
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(release, ('foreign-release','unknown',main,'c'*64,'d'*64))
        db.execute(release, ('release','project',main,'c'*64,'d'*64))
        db.execute("INSERT INTO release_publications VALUES ('project','site','release',1,1)")
        for table in ['verification_requests','verification_results','release_records']:
            with pytest.raises(sqlite3.IntegrityError): db.execute(f'DELETE FROM {table}')
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE verification_results SET outcome='failed'")
        assert not db.execute('PRAGMA foreign_key_check').fetchall()


def test_failed_verification_cannot_back_release(legacy):
    path, backup = legacy
    migrate(path, backup, target_version=2)
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        main, = db.execute('SELECT id FROM revision_workspaces WHERE heat_id IS NULL').fetchone()
        db.execute('INSERT INTO revision_artifacts VALUES (?,?,14,1)', ('a'*64,'b'*64))
        db.execute("INSERT INTO revision_records VALUES ('root',?,'project',NULL,?,?,NULL,1)", (main,'a'*64,'b'*64))
        db.execute("INSERT INTO verification_requests VALUES ('check',?,'project','root',?,'[]',?,'runner','user',10,20)", (main,'c'*64,'d'*64))
        db.execute("INSERT INTO verification_results VALUES ('check',?,'root',?,?,'failed',1,0,'[]',15)", (main,'c'*64,'d'*64))
        with pytest.raises(sqlite3.IntegrityError, match='release_requires_passing_evidence'):
            db.execute("INSERT INTO release_records VALUES ('release','project',?,'root','check',?,?,'owner','user',NULL,16)", (main,'c'*64,'d'*64))


def test_process_death_during_release_ddl_recovers_v1(legacy, tmp_path):
    path, baseline = legacy
    migrate(path, baseline)
    backup = tmp_path / 'before-crash-v2.db'
    script = '''
import os,sys
from pathlib import Path
from app.migrations import migrate,release_v2
original=release_v2.apply
def crash(db):
    original(db)
    os._exit(42)
release_v2.apply=crash
migrate(Path(sys.argv[1]),Path(sys.argv[2]),target_version=2)
'''
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    result = subprocess.run([sys.executable,'-c',script,str(path),str(backup)], env=env, capture_output=True, timeout=30)
    assert result.returncode == 42, result.stderr
    assert verify(path) == 1 and verify_backup(backup, expected_version=1)
    assert migrate(path,tmp_path/'after-release-crash.db',target_version=2).applied
