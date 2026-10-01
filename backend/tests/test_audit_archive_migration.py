from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from app.migrations import migrate, verify, verify_backup, MigrationError
from app.audit_retention import RetentionRepository, RetentionError
from test_revision_migrations import legacy
from test_audit_retention_migration import dump
from test_retention_plan import planned, reader, audited_release, release, ledger
from test_audit_retention import args


@pytest.mark.parametrize('source', range(9))
def test_source_backup_full_restore_empty_ledgers_and_replay(legacy, tmp_path, source):
    path, initial = legacy
    if source: migrate(path, initial, target_version=source)
    before = dump(path)
    saved = tmp_path/'before-nine.db'
    result = migrate(path, saved, target_version=9)
    assert result.applied and verify(path) == 9
    assert verify_backup(saved, expected_version=source) == result.backup_sha256
    restored = tmp_path/'restored.db'
    with sqlite3.connect(saved) as backup, sqlite3.connect(restored) as recovery:
        backup.backup(recovery)
    assert verify(restored) == source and dump(restored) == before
    assert not migrate(path, saved, target_version=9).applied
    with sqlite3.connect(path) as db:
        for table in ('security_audit_archives','security_audit_archive_recoveries'):
            assert db.execute('SELECT count(*) FROM '+table).fetchone() == (0,)
    assert RetentionRepository(path).policies() == ()


def manifest(**changes):
    row = dict(archive_id='archive',operator_id='operator',policy_id='policy',policy_generation=1,archive_store_id='store',
        format_version=1,coverage='business_audit_events_v1',scope_kind='account',scope_id='user',event_kind='console.session.created',
        context_sha256='a'*64,plan_sha256='b'*64,archive_sha256='c'*64,archive_bytes=1000,payload_sha256='d'*64,payload_bytes=500,
        event_count=1,after_sequence=0,upper_sequence=1,observed_at=100,registered_at=101)
    return dict(row, **changes)


def insert(db, row):
    db.execute('INSERT INTO security_audit_archives ('+','.join(row)+') VALUES ('+','.join('?' for _ in row)+')', tuple(row.values()))


@pytest.fixture
def authority(legacy):
    path, backup = legacy
    migrate(path, backup, target_version=9)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO security_audit_retention_policies VALUES ('policy','account','user','console.session.created',1,'active',1,'store',100,100)")
    return path


@pytest.mark.parametrize('changes', [dict(policy_generation=2),dict(policy_id='missing'),dict(archive_store_id='other'),
    dict(scope_id='other'),dict(event_kind='release.published'),dict(context_sha256='bad'),dict(archive_bytes=262145),
    dict(payload_bytes=1000),dict(event_count=101),dict(upper_sequence=0),dict(observed_at=99),dict(registered_at=99),
    dict(format_version=2),dict(coverage='all_events'),dict(archive_id=None),dict(event_count=1.5)])
def test_invalid_metadata_cannot_be_registered(authority, changes):
    with sqlite3.connect(authority) as db:
        with pytest.raises(sqlite3.IntegrityError): insert(db, manifest(**changes))


def test_holds_and_paused_policy_prevent_registration(authority):
    with sqlite3.connect(authority) as db:
        db.execute("INSERT INTO security_audit_retention_holds VALUES ('hold','policy','legal','active',1,100,100)")
        with pytest.raises(sqlite3.IntegrityError): insert(db, manifest())
        db.execute("UPDATE security_audit_retention_policies SET generation=2,state='paused'")
        db.execute("UPDATE security_audit_retention_holds SET policy_generation=2,state='released'")
        with pytest.raises(sqlite3.IntegrityError): insert(db, manifest(policy_generation=2))


def test_immutable_ledgers_and_exact_recovery_relationship(authority):
    with sqlite3.connect(authority) as db:
        db.execute('PRAGMA foreign_keys=ON')
        insert(db, manifest())
        recovery = ['recovery','archive','verifier','c'*64,'d'*64,1,102]
        for index, replacement in ((1,'missing'),(3,'e'*64),(4,'e'*64),(5,2),(6,100)):
            wrong = recovery.copy()
            wrong[index] = replacement
            with pytest.raises(sqlite3.IntegrityError):
                db.execute('INSERT INTO security_audit_archive_recoveries VALUES (?,?,?,?,?,?,?)', wrong)
        db.execute('INSERT INTO security_audit_archive_recoveries VALUES (?,?,?,?,?,?,?)', recovery)
        for table in ('security_audit_archives','security_audit_archive_recoveries'):
            for sql in ('DELETE FROM '+table, 'INSERT OR REPLACE INTO '+table+' SELECT * FROM '+table):
                with pytest.raises(sqlite3.IntegrityError): db.execute(sql)
        with pytest.raises(sqlite3.IntegrityError): db.execute("UPDATE security_audit_archives SET archive_bytes=999")
        with pytest.raises(sqlite3.IntegrityError): db.execute("UPDATE security_audit_archive_recoveries SET verifier_id='other'")
        row = manifest(archive_id='alternate-key-replacement')
        with pytest.raises(sqlite3.IntegrityError):
            db.execute('INSERT OR REPLACE INTO security_audit_archives VALUES ('+','.join('?' for _ in row)+')', tuple(row.values()))
        assert db.execute('SELECT archive_id FROM security_audit_archives').fetchall() == [('archive',)]


def test_late_ddl_failure_rolls_back_full_eight(legacy, tmp_path, monkeypatch):
    from app.migrations import audit_archives_v9
    path, initial = legacy
    migrate(path, initial, target_version=8)
    before = dump(path)
    original = audit_archives_v9.apply
    def fail(db):
        original(db)
        raise sqlite3.OperationalError('late failure')
    monkeypatch.setattr(audit_archives_v9, 'apply', fail)
    with pytest.raises(MigrationError): migrate(path, tmp_path/'saved.db', target_version=9)
    assert verify(path) == 8 and dump(path) == before
    assert verify_backup(tmp_path/'saved.db', expected_version=8)


@pytest.mark.parametrize('phase', ['before','after'])
def test_real_process_exit_around_migration_commit(legacy, tmp_path, phase):
    path, initial = legacy
    migrate(path, initial, target_version=8)
    before = dump(path)
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
migrate(Path(sys.argv[1]),Path(sys.argv[2]),target_version=9)
'''
    backup = tmp_path/'before-nine.db'
    result = subprocess.run([sys.executable,'-c',script,str(path),str(backup),phase],
        cwd=Path(__file__).resolve().parents[1],capture_output=True,timeout=15)
    assert result.returncode == (71 if phase == 'before' else 72), result.stderr.decode()
    assert verify(path) == (8 if phase == 'before' else 9)
    if phase == 'before': assert dump(path) == before
    assert verify_backup(backup, expected_version=8)
    assert migrate(path, tmp_path/'retry.db', target_version=9).applied == (phase == 'before')


def test_populated_eight_history_and_cli_upgrade_preserved(planned, tmp_path):
    path, repo = planned
    repo.execute(**args('place_hold',1,'hold',hold_id='hold',hold_kind='legal'))
    with sqlite3.connect(path) as db:
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name<>'atom_schema_migrations'")]
        before = {table: db.execute('SELECT * FROM '+table).fetchall() for table in tables}
    saved = tmp_path/'populated-eight.db'
    result = subprocess.run([sys.executable,'-m','app.migrations',str(path),'--backup',str(saved),'--target-version','9'],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=15)
    assert result.returncode == 0 and not result.stderr
    assert verify(path) == 9 and verify_backup(saved, expected_version=8)
    with sqlite3.connect(path) as db:
        assert {table: db.execute('SELECT * FROM '+table).fetchall() for table in tables} == before
    assert repo.plan(policy_id='policy',expected_generation=2)['blocked_count'] == 3
