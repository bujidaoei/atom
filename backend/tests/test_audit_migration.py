import sqlite3
from pathlib import Path
import subprocess
import sys

import pytest
from app.migrations import migrate, verify, verify_backup, MigrationError
from test_revision_migrations import legacy


@pytest.mark.parametrize('source_version',[0,1,2,3,4])
def test_audit_upgrade_preserves_backup_and_prior_history(legacy,tmp_path,source_version):
    path,baseline=legacy
    if source_version:migrate(path,baseline,target_version=source_version)
    backup=tmp_path/'before-audit.db'
    result=migrate(path,backup,target_version=5)
    assert result.version==5 and verify(path)==5
    assert verify_backup(backup,expected_version=source_version)==result.backup_sha256
    assert not migrate(path,backup,target_version=5).applied
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT version FROM atom_schema_migrations ORDER BY version').fetchall()==[(i,) for i in range(1,6)]
        assert db.execute('SELECT prompt FROM projects').fetchone()==('actual preserved input',)
        assert db.execute('SELECT count(*) FROM security_audit_events').fetchone()==(0,)
    restored=tmp_path/'restored.db'
    with sqlite3.connect(backup) as source,sqlite3.connect(restored) as target:source.backup(target)
    assert verify(restored)==source_version


def insert(db,event='a'*32):
    db.execute("INSERT INTO security_audit_events(event_id,schema_version,event_kind,occurred_at,actor_kind,actor_id,scope_kind,scope_id,affected_count) VALUES (?,1,'console.account_sessions.revoked',100,'user','user','account','user',2)",(event,))


def test_audit_immutability_and_delivery_constraints(legacy):
    path,backup=legacy
    migrate(path,backup,target_version=5)
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        insert(db)
        for sql in ["UPDATE security_audit_events SET occurred_at=101", "DELETE FROM security_audit_events",
            "INSERT OR REPLACE INTO security_audit_events SELECT * FROM security_audit_events"]:
            with pytest.raises(sqlite3.IntegrityError):db.execute(sql)
        assert db.execute('SELECT occurred_at FROM security_audit_events').fetchone()==(100,)
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO security_audit_delivery(event_id,destination_id,state,next_attempt_at) VALUES (?,'sink','pending',100)",('b'*32,))
        db.execute("INSERT INTO security_audit_delivery(event_id,destination_id,state,next_attempt_at) VALUES (?,'sink','pending',100)",('a'*32,))
        with pytest.raises(sqlite3.IntegrityError):db.execute("UPDATE security_audit_delivery SET state='leased'")
        db.execute("UPDATE security_audit_delivery SET state='leased',attempt=1,lease_owner=?,lease_expires_at=120",('c'*32,))
        with pytest.raises(sqlite3.IntegrityError):db.execute('UPDATE security_audit_delivery SET attempt=0')
        db.execute("UPDATE security_audit_delivery SET state='delivered',lease_owner=NULL,lease_expires_at=NULL,delivered_at=110")
        with pytest.raises(sqlite3.IntegrityError):db.execute("UPDATE security_audit_delivery SET next_attempt_at=200")
        with pytest.raises(sqlite3.IntegrityError):db.execute("INSERT OR REPLACE INTO security_audit_delivery SELECT * FROM security_audit_delivery")
        with pytest.raises(sqlite3.IntegrityError):db.execute("DELETE FROM security_audit_delivery")


def test_failed_audit_ddl_rolls_back_to_v4(legacy,tmp_path,monkeypatch):
    from app.migrations import audit_v5
    path,backup=legacy
    migrate(path,backup,target_version=4)
    original=audit_v5.apply
    def fail(db):
        original(db)
        raise sqlite3.OperationalError('test_late_ddl_failure')
    monkeypatch.setattr(audit_v5,'apply',fail)
    with pytest.raises(MigrationError):migrate(path,tmp_path/'before.db',target_version=5)
    assert verify(path)==4 and verify_backup(tmp_path/'before.db',expected_version=4)


def test_process_exit_before_commit_preserves_source_and_retry(legacy,tmp_path):
    path,backup=legacy
    migrate(path,backup,target_version=4)
    code="""
import os,sys
from pathlib import Path
from app.migrations import migrate,audit_v5
original=audit_v5.apply
def crash(db):
    original(db)
    os._exit(73)
audit_v5.apply=crash
migrate(Path(sys.argv[1]),Path(sys.argv[2]),target_version=5)
"""
    result=subprocess.run([sys.executable,'-c',code,str(path),str(tmp_path/'crash-backup.db')],
        cwd=Path(__file__).resolve().parents[1],capture_output=True,timeout=15)
    assert result.returncode==73,result.stderr.decode()
    assert verify(path)==4
    assert verify_backup(tmp_path/'crash-backup.db',expected_version=4)
    assert migrate(path,tmp_path/'retry.db',target_version=5).applied
