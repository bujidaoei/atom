"""Schema/guard tests use synthetic metadata; not proof of authorized archive pruning."""
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app.migrations import migrate, verify, verify_backup, MigrationError
from app.migrations.audit_pruning_v11 import RECEIPTS, MARKERS
from test_revision_migrations import legacy
from test_audit_retention_migration import dump
from test_audit_archive_migration import authority
from test_audit_isolated_migration import isolated, record, receipt


@pytest.mark.parametrize('source',range(11))
def test_full_source_backup_replay_and_no_default_authority(legacy,tmp_path,source):
    path,initial=legacy
    if source:migrate(path,initial,target_version=source)
    before=dump(path)
    saved=tmp_path/'before-eleven.db'
    result=migrate(path,saved,target_version=11)
    assert result.applied and verify(path)==11
    assert verify_backup(saved,expected_version=source)==result.backup_sha256
    assert dump(saved)==before
    assert not migrate(path,saved,target_version=11).applied
    with sqlite3.connect(path) as db:
        for table in (RECEIPTS,MARKERS):
            assert db.execute('SELECT count(*) FROM '+table).fetchone()==(0,)


@pytest.fixture
def guarded(isolated,tmp_path):
    with sqlite3.connect(isolated) as db:
        record(db,receipt())
        db.execute("INSERT INTO security_audit_events(sequence,event_id,schema_version,event_kind,occurred_at,actor_kind,actor_id,scope_kind,scope_id,affected_count) "
            "VALUES (1,?,1,'console.session.created',100,'user','user','account','user',1)",('1'*32,))
        db.execute("INSERT INTO security_audit_destinations(destination_id,scope_kind,scope_id,generation,state,created_at,updated_at) "
            "VALUES ('sink','account','user',1,'active',100,100)")
    migrate(isolated,tmp_path/'ten.db',target_version=11)
    return isolated


def authorize(db,allowed=True):
    db.create_function('atom_prune_authorized',3,lambda command,event,sequence:
        int(allowed and command=='command' and (event,sequence) in (('',0),('1'*32,1))))


def anchors(db):
    db.execute('INSERT INTO '+RECEIPTS+" VALUES ('command','operator',?,'archive','new','policy',1,?,?,1,103)",
               ('0'*64,'a'*64,'d'*64))
    db.execute('INSERT INTO '+MARKERS+" VALUES (1,?,'account','user','console.session.created','command')",('1'*32,))


@pytest.mark.parametrize('mode',['missing','denied','wrong-membership'])
def test_no_default_or_wrong_connection_authority(guarded,mode):
    before=dump(guarded)
    with sqlite3.connect(guarded) as db:
        if mode=='denied':authorize(db,False)
        if mode=='wrong-membership':db.create_function('atom_prune_authorized',3,lambda command,event,seq:int(seq==2))
        with pytest.raises(sqlite3.DatabaseError):anchors(db)
        with pytest.raises(sqlite3.DatabaseError):db.execute('DELETE FROM security_audit_events')
    assert dump(guarded)==before


def test_exact_guarded_delete_immutable_markers_and_identity_nonreuse(guarded):
    with sqlite3.connect(guarded) as db:
        db.execute('PRAGMA foreign_keys=ON')
        event=db.execute('SELECT * FROM security_audit_events WHERE sequence=1').fetchone()
        db.execute("INSERT INTO security_audit_delivery(event_id,destination_id,state,next_attempt_at,delivered_at) VALUES (?,'sink','delivered',100,101)",('1'*32,))
        authorize(db)
        anchors(db)
        with pytest.raises(sqlite3.IntegrityError):db.execute('DELETE FROM security_audit_events')
        db.execute('DELETE FROM security_audit_delivery')
        db.execute('DELETE FROM security_audit_events')
        for table in (RECEIPTS,MARKERS):
            with pytest.raises(sqlite3.IntegrityError):db.execute('DELETE FROM '+table)
            with pytest.raises(sqlite3.IntegrityError):db.execute('INSERT OR REPLACE INTO '+table+' SELECT * FROM '+table)
        with pytest.raises(sqlite3.IntegrityError):db.execute('UPDATE '+MARKERS+" SET scope_id='other'")
        # Reusing either identity is forbidden, independently of AUTOINCREMENT.
        for index,value in ((0,2),(1,'2'*32)):
            changed=list(event);changed[index]=value
            with pytest.raises(sqlite3.IntegrityError):
                db.execute('INSERT INTO security_audit_events VALUES ('+','.join('?' for _ in event)+')',changed)
        db.execute("INSERT INTO security_audit_events(event_id,schema_version,event_kind,occurred_at,actor_kind,actor_id,scope_kind,scope_id,affected_count) "
            "VALUES (?,1,'console.session.created',104,'user','user','account','user',1)",('2'*32,))
        assert db.execute('SELECT sequence FROM security_audit_events').fetchone()==(2,)
    assert verify(guarded)==11
    with sqlite3.connect(guarded) as ordinary:
        with pytest.raises(sqlite3.DatabaseError):ordinary.execute('DELETE FROM security_audit_events')


@pytest.mark.parametrize('state',['pending','leased'])
def test_unsettled_delivery_cannot_be_removed_even_with_membership(guarded,state):
    with sqlite3.connect(guarded) as db:
        db.execute("INSERT INTO security_audit_delivery(event_id,destination_id,state,attempt,next_attempt_at,lease_owner,lease_expires_at) VALUES (?,'sink',?,1,100,?,?)",
            ('1'*32,state,'3'*32 if state=='leased' else None,200 if state=='leased' else None))
        authorize(db);anchors(db)
        with pytest.raises(sqlite3.IntegrityError):db.execute('DELETE FROM security_audit_delivery')
        with pytest.raises(sqlite3.IntegrityError):db.execute('DELETE FROM security_audit_events')


@pytest.mark.parametrize('change',["UPDATE security_audit_retention_policies SET generation=2",
    "UPDATE security_audit_retention_policies SET state='paused',generation=2",
    "INSERT INTO security_audit_retention_holds VALUES ('hold','policy','legal','active',1,100,100)"])
def test_stale_policy_or_hold_denies_evidence(guarded,change):
    with sqlite3.connect(guarded) as db:
        db.execute(change)
        authorize(db)
        with pytest.raises(sqlite3.IntegrityError):anchors(db)


def test_late_migration_failure_restores_original_guards(isolated,tmp_path,monkeypatch):
    from app.migrations import audit_pruning_v11
    before=dump(isolated)
    original=audit_pruning_v11.apply
    def fail(db):
        original(db)
        raise sqlite3.OperationalError('late failure')
    monkeypatch.setattr(audit_pruning_v11,'apply',fail)
    with pytest.raises(MigrationError):migrate(isolated,tmp_path/'saved.db',target_version=11)
    assert verify(isolated)==10 and dump(isolated)==before
    assert verify_backup(tmp_path/'saved.db',expected_version=10)


@pytest.mark.parametrize('phase',['before','after'])
def test_real_exit_around_new_schema_commit(isolated,tmp_path,phase):
    before=dump(isolated)
    script='''
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
migrate(Path(sys.argv[1]),Path(sys.argv[2]),target_version=11)
'''
    saved=tmp_path/'crash.db'
    result=subprocess.run([sys.executable,'-c',script,str(isolated),str(saved),phase],
        cwd=Path(__file__).resolve().parents[1],capture_output=True,timeout=15)
    assert result.returncode==(71 if phase=='before' else 72),result.stderr.decode()
    assert verify(isolated)==(10 if phase=='before' else 11)
    if phase=='before':assert dump(isolated)==before
    assert verify_backup(saved,expected_version=10)
    assert migrate(isolated,tmp_path/'retry.db',target_version=11).applied==(phase=='before')


def test_serving_and_archive_owner_still_refuse_unaccepted_schema(guarded):
    from app.access_repository import AccessRepository, AccessError
    from app.audit_retention import RetentionRepository, RetentionError
    with pytest.raises(AccessError):AccessRepository(guarded)
    with pytest.raises(RetentionError):RetentionRepository(guarded)
