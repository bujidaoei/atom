"""Offline policy/hold constraints; no application retention authority yet."""
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from app.migrations import migrate, verify, verify_backup, MigrationError
from test_revision_migrations import legacy


def dump(path):
    with sqlite3.connect(path) as db:
        return list(db.iterdump())


@pytest.mark.parametrize('source_version', range(8))
def test_backup_restore_upgrade_and_no_implicit_policy(legacy, tmp_path, source_version):
    path, baseline = legacy
    if source_version:
        migrate(path, baseline, target_version=source_version)
    before = dump(path)
    backup = tmp_path/'before-eight.db'
    result = migrate(path, backup, target_version=8)
    assert result.applied and verify(path) == 8
    assert verify_backup(backup, expected_version=source_version) == result.backup_sha256
    assert dump(backup) == before
    restored = tmp_path/'restored.db'
    with sqlite3.connect(backup) as origin, sqlite3.connect(restored) as target:
        origin.backup(target)
    assert verify(restored) == source_version and dump(restored) == before
    assert not migrate(path, backup, target_version=8).applied
    with sqlite3.connect(path) as db:
        for table in ('policies','holds','commands'):
            assert db.execute('SELECT count(*) FROM security_audit_retention_'+table).fetchone() == (0,)


def policy(db):
    db.execute("INSERT INTO security_audit_retention_policies VALUES ('policy','account','user','console.session.created',1,'paused',86400,'archive',100,100)")


def receipt(db, command, generation, action, *, hold=None, kind=None, state=None):
    db.execute('INSERT INTO security_audit_retention_commands VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (command,'policy','operator',action,'a'*64,generation-1,generation,'paused',86400,'archive',hold,kind,state,100))


def test_policy_hold_and_receipt_constraints(legacy):
    path, backup = legacy
    migrate(path, backup, target_version=8)
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        policy(db)
        receipt(db, 'create', 1, 'create_policy')
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO security_audit_retention_holds VALUES ('unfenced','policy','legal','active',1,100,100)")
        for sql in (
            "UPDATE security_audit_retention_policies SET min_age_seconds=10",
            "UPDATE security_audit_retention_policies SET scope_id='other',generation=2",
            "UPDATE security_audit_retention_policies SET min_age_seconds=0,generation=2",
            "DELETE FROM security_audit_retention_policies",
            "INSERT OR REPLACE INTO security_audit_retention_policies VALUES ('replacement','account','user','console.session.created',1,'paused',1,'archive',100,100)",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(sql)
        # Independent holds remain present: releasing one cannot clear the other.
        for generation, identity, kind in ((2,'legal-hold','legal'), (3,'incident-hold','operational')):
            db.execute('UPDATE security_audit_retention_policies SET generation=?', (generation,))
            db.execute('INSERT INTO security_audit_retention_holds VALUES (?,?,?,?,?,?,?)',
                (identity,'policy',kind,'active',generation,100,100))
            receipt(db, identity, generation, 'place_hold', hold=identity, kind=kind, state='active')
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE security_audit_retention_holds SET state='released',policy_generation=4 WHERE hold_id='legal-hold'")
        db.execute('UPDATE security_audit_retention_policies SET generation=4')
        db.execute("UPDATE security_audit_retention_holds SET state='released',policy_generation=4 WHERE hold_id='legal-hold'")
        receipt(db, 'release', 4, 'release_hold', hold='legal-hold', kind='legal', state='released')
        assert db.execute("SELECT hold_id FROM security_audit_retention_holds WHERE state='active'").fetchall() == [('incident-hold',)]
        for sql in (
            "DELETE FROM security_audit_retention_holds",
            "UPDATE security_audit_retention_holds SET state='active',policy_generation=5 WHERE hold_id='legal-hold'",
            "INSERT OR REPLACE INTO security_audit_retention_holds SELECT * FROM security_audit_retention_holds",
            "DELETE FROM security_audit_retention_commands",
            "UPDATE security_audit_retention_commands SET operator_id='another'",
            "INSERT OR REPLACE INTO security_audit_retention_commands SELECT * FROM security_audit_retention_commands",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(sql)


def test_inconsistent_and_nullable_receipts_rejected(legacy):
    path, backup = legacy
    migrate(path, backup, target_version=8)
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        policy(db)
        with pytest.raises(sqlite3.IntegrityError):
            receipt(db, 'stale', 2, 'update_policy')
        db.execute('UPDATE security_audit_retention_policies SET generation=2')
        db.execute("INSERT INTO security_audit_retention_holds VALUES ('hold','policy','legal','active',2,100,100)")
        with pytest.raises(sqlite3.IntegrityError):
            receipt(db, 'null-state', 2, 'place_hold', hold='hold', kind='legal')
        with pytest.raises(sqlite3.IntegrityError):
            receipt(db, 'wrong-kind', 2, 'place_hold', hold='hold', kind='operational', state='active')
        receipt(db, 'actual', 2, 'place_hold', hold='hold', kind='legal', state='active')
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT OR REPLACE INTO security_audit_retention_commands SELECT 'replacement',policy_id,operator_id,action,request_sha256,expected_generation,generation,state,min_age_seconds,archive_store_id,hold_id,hold_kind,hold_state,occurred_at FROM security_audit_retention_commands")


def test_late_ddl_failure_preserves_seven(legacy, tmp_path, monkeypatch):
    from app.migrations import audit_retention_v8
    path, backup = legacy
    migrate(path, backup, target_version=7)
    before = dump(path)
    original = audit_retention_v8.apply
    def fail(db):
        original(db)
        raise sqlite3.OperationalError('injected_late_failure')
    monkeypatch.setattr(audit_retention_v8, 'apply', fail)
    with pytest.raises(MigrationError):
        migrate(path, tmp_path/'late.db', target_version=8)
    assert verify(path) == 7 and dump(path) == before
    assert verify_backup(tmp_path/'late.db', expected_version=7)


@pytest.mark.parametrize('phase', ['before','after'])
def test_actual_migration_process_exit_and_retry(legacy, tmp_path, phase):
    path, backup = legacy
    migrate(path, backup, target_version=7)
    before = dump(path)
    code = '''
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
migrate(Path(sys.argv[1]),Path(sys.argv[2]),target_version=8)
'''
    saved = tmp_path/'before-eight.db'
    result = subprocess.run([sys.executable, '-c', code, str(path), str(saved), phase],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=15)
    assert result.returncode == (71 if phase == 'before' else 72), result.stderr.decode()
    assert verify(path) == (7 if phase == 'before' else 8)
    if phase == 'before':
        assert dump(path) == before
    assert verify_backup(saved, expected_version=7)
    assert migrate(path, tmp_path/'retry-eight.db', target_version=8).applied == (phase == 'before')


def test_populated_audit_and_governance_history_unchanged(legacy, tmp_path):
    from app.access_repository import AccessRepository, AccessError
    from app.audit_governance import AuditGovernanceRepository
    path, baseline = legacy
    migrate(path, baseline, target_version=7)
    AccessRepository(path).create_console_session(user_id='user', lifetime_seconds=60)
    registry = AuditGovernanceRepository(path)
    registry.execute(command_id='register', operator_id='operator', destination_id='sink', scope_kind='account',
        scope_id='user', action='register', expected_generation=0)
    tables = ('security_audit_events','security_audit_destinations','security_audit_destination_commands','console_sessions')
    with sqlite3.connect(path) as db:
        before = {table: db.execute('SELECT * FROM '+table).fetchall() for table in tables}
    migrate(path, tmp_path/'seven.db', target_version=8)
    with sqlite3.connect(path) as db:
        assert {table: db.execute('SELECT * FROM '+table).fetchall() for table in tables} == before
    # Offline-only until separately verified consumer compatibility is implemented.
    with pytest.raises(AccessError, match='access_schema_required'):
        AccessRepository(path)
