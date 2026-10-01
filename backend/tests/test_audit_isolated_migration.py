from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from app.migrations import migrate, verify, verify_backup, MigrationError
from app.migrations.audit_recovery_v10 import TABLE
from test_revision_migrations import legacy
from test_audit_retention_migration import dump
from test_audit_archive_migration import authority, manifest, insert


@pytest.mark.parametrize('source', range(10))
def test_every_source_backup_restore_and_replay(legacy, tmp_path, source):
    path, initial = legacy
    if source:
        migrate(path, initial, target_version=source)
    before = dump(path)
    saved = tmp_path/'before-ten.db'
    result = migrate(path, saved, target_version=10)
    assert result.applied and verify(path) == 10
    assert verify_backup(saved, expected_version=source) == result.backup_sha256
    restored = tmp_path/'restored.db'
    with sqlite3.connect(saved) as backup, sqlite3.connect(restored) as recovery:
        backup.backup(recovery)
    assert verify(restored) == source and dump(restored) == before
    assert not migrate(path, saved, target_version=10).applied
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM '+TABLE).fetchone() == (0,)


@pytest.fixture
def isolated(authority, tmp_path):
    with sqlite3.connect(authority) as db:
        insert(db, manifest())
        db.execute("INSERT INTO security_audit_archive_recoveries VALUES ('old','archive','verifier',?,?,1,102)",
                   ('c'*64, 'd'*64))
    migrate(authority, tmp_path/'nine.db', target_version=10)
    return authority


def receipt(**changes):
    return dict(dict(recovery_id='new',archive_id='archive',verifier_id='verifier',protocol='audit-recovery-v2',
        image='sha256:'+'a'*64,policy_digest='b'*64,attempt_id='e'*32,archive_sha256='c'*64,
        payload_sha256='d'*64,event_count=1,result_sha256='f'*64,verified_at=102), **changes)


def record(db, row, *, replace=False):
    db.execute(('INSERT OR REPLACE' if replace else 'INSERT')+' INTO '+TABLE+' ('+','.join(row)+') VALUES ('+
               ','.join('?' for _ in row)+')', tuple(row.values()))


@pytest.mark.parametrize('changes', [dict(protocol='audit-recovery-v1'),dict(image='latest'),
    dict(image='sha256:'+'G'*64),dict(policy_digest='a'*63),dict(attempt_id='x'*32),dict(attempt_id=None),
    dict(result_sha256=''),dict(archive_id='missing'),dict(archive_sha256='e'*64),dict(payload_sha256='e'*64),
    dict(event_count=2),dict(event_count=1.5),dict(verified_at=100),dict(recovery_id='bad/id')])
def test_invalid_provenance_and_archive_relationship_denied(isolated, changes):
    with sqlite3.connect(isolated) as db:
        db.execute('PRAGMA foreign_keys=ON')
        with pytest.raises(sqlite3.IntegrityError):
            record(db, receipt(**changes))
        assert db.execute('SELECT count(*) FROM '+TABLE).fetchone() == (0,)


def test_old_receipts_not_promoted_and_new_rows_immutable(isolated):
    with sqlite3.connect(isolated) as db:
        assert db.execute('SELECT count(*) FROM '+TABLE).fetchone() == (0,)
        old = db.execute('SELECT * FROM security_audit_archive_recoveries').fetchall()
        assert old == [('old','archive','verifier','c'*64,'d'*64,1,102)]
        record(db, receipt())
        for sql in ('DELETE FROM '+TABLE, "UPDATE "+TABLE+" SET protocol='audit-recovery-v2'"):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(sql)
        for changes in ({}, dict(recovery_id='alternate')):
            with pytest.raises(sqlite3.IntegrityError):
                record(db, receipt(**changes), replace=True)
        record(db, receipt(recovery_id='second',attempt_id='9'*32))
        assert db.execute('SELECT count(*) FROM '+TABLE).fetchone() == (2,)
        assert db.execute('SELECT * FROM security_audit_archive_recoveries').fetchall() == old


def test_late_failure_rolls_back_populated_history(authority, tmp_path, monkeypatch):
    from app.migrations import audit_recovery_v10
    before = dump(authority)
    original = audit_recovery_v10.apply
    def fail(db):
        original(db)
        raise sqlite3.OperationalError('late failure')
    monkeypatch.setattr(audit_recovery_v10, 'apply', fail)
    saved = tmp_path/'failed.db'
    with pytest.raises(MigrationError):
        migrate(authority, saved, target_version=10)
    assert verify(authority) == 9 and dump(authority) == before
    assert verify_backup(saved, expected_version=9)


@pytest.mark.parametrize('phase', ['before','after'])
def test_actual_exit_around_commit(authority, tmp_path, phase):
    before = dump(authority)
    script = '''
import os,sqlite3,sys
from pathlib import Path
from app.migrations import migrate
original=sqlite3.connect
class Connection(sqlite3.Connection):
    def execute(self,sql,*args,**kwargs):
        if sql=='COMMIT' and sys.argv[3]=='before':os._exit(71)
        result=super().execute(sql,*args,**kwargs)
        if sql=='COMMIT' and sys.argv[3]=='after':os._exit(72)
        return result
sqlite3.connect=lambda *args,**kwargs:original(*args,**dict(kwargs,factory=Connection))
migrate(Path(sys.argv[1]),Path(sys.argv[2]),target_version=10)
'''
    saved = tmp_path/'crash.db'
    result = subprocess.run([sys.executable,'-c',script,str(authority),str(saved),phase],
        cwd=Path(__file__).resolve().parents[1],capture_output=True,timeout=15)
    assert result.returncode == (71 if phase == 'before' else 72), result.stderr.decode()
    assert verify(authority) == (9 if phase == 'before' else 10)
    if phase == 'before':
        assert dump(authority) == before
    assert verify_backup(saved, expected_version=9)
    assert migrate(authority,tmp_path/'retry.db',target_version=10).applied == (phase == 'before')


@pytest.mark.parametrize('tamper', ['schema', 'journal'])
def test_tampered_schema_or_journal_rejected(isolated, tamper):
    with sqlite3.connect(isolated) as db:
        if tamper == 'schema':
            db.execute('DROP TRIGGER '+TABLE+'_no_delete')
        else:
            db.execute("UPDATE atom_schema_migrations SET migration_hash=? WHERE version=10", ('0'*64,))
    with pytest.raises(MigrationError):
        verify(isolated)


def test_cli_preserves_all_existing_rows_and_backup_of_new_receipts(authority, tmp_path):
    from app.migrations import backup_database
    with sqlite3.connect(authority) as db:
        insert(db, manifest())
        db.execute("INSERT INTO security_audit_archive_recoveries VALUES ('old','archive','verifier',?,?,1,102)",
                   ('c'*64,'d'*64))
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        before = {name: db.execute('SELECT * FROM '+name).fetchall() for name in tables}
    saved = tmp_path/'cli-nine.db'
    result = subprocess.run([sys.executable,'-m','app.migrations',str(authority),'--backup',str(saved),
        '--target-version','10'],cwd=Path(__file__).resolve().parents[1],capture_output=True,timeout=15)
    assert result.returncode == 0 and not result.stderr
    assert verify(authority) == 10 and verify_backup(saved, expected_version=9)
    with sqlite3.connect(authority) as db:
        for name, rows in before.items():
            current = db.execute('SELECT * FROM '+name).fetchall()
            assert (current[:9] if name == 'atom_schema_migrations' else current) == rows
        record(db, receipt())
    latest = tmp_path/'ten.db'
    result = backup_database(authority, latest)
    assert result.version == 10 and verify_backup(latest, expected_version=10) == result.sha256
    assert dump(latest) == dump(authority)
