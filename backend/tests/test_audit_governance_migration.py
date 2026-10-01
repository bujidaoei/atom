"""Offline registry migration evidence; does not claim runtime v6 compatibility."""
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app.migrations import MigrationError, migrate, verify, verify_backup
from test_revision_migrations import legacy


def history(path, *, conflict=False):
    with sqlite3.connect(path) as db:
        for index, scope in enumerate(('user', 'other' if conflict else 'user')):
            event = str(index + 1) * 32
            db.execute("INSERT INTO security_audit_events(event_id,schema_version,event_kind,occurred_at,actor_kind,actor_id,scope_kind,scope_id,affected_count) VALUES (?,1,'console.account_sessions.revoked',100,'user',?,'account',?,1)", (event, scope, scope))
            db.execute("INSERT INTO security_audit_delivery(event_id,destination_id,state,next_attempt_at) VALUES (?,'removed-sink','pending',100)", (event,))


def dump(path):
    with sqlite3.connect(path) as db:
        return '\n'.join(db.iterdump())


@pytest.mark.parametrize('source_version', range(6))
def test_upgrade_backup_restore_and_replay(legacy, tmp_path, source_version):
    path, baseline = legacy
    if source_version:
        migrate(path, baseline, target_version=source_version)
    before = dump(path)
    backup = tmp_path / 'before-six.db'
    result = migrate(path, backup, target_version=6)
    assert result.applied and verify(path) == 6
    assert verify_backup(backup, expected_version=source_version) == result.backup_sha256
    assert dump(backup) == before
    assert not migrate(path, backup, target_version=6).applied
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT version FROM atom_schema_migrations ORDER BY version').fetchall() == [(i,) for i in range(1, 7)]
        assert db.execute('SELECT prompt FROM projects').fetchone() == ('actual preserved input',)
    restored = tmp_path / 'restored.db'
    with sqlite3.connect(backup) as source, sqlite3.connect(restored) as target:
        source.backup(target)
    assert verify(restored) == source_version and dump(restored) == before
    assert verify_backup(path, expected_version=6)


def test_historical_identity_preserved_and_active_scope_required(legacy, tmp_path):
    path, baseline = legacy
    migrate(path, baseline, target_version=5)
    history(path)
    with sqlite3.connect(path) as db:
        events = db.execute('SELECT * FROM security_audit_events').fetchall()
        deliveries = db.execute('SELECT * FROM security_audit_delivery').fetchall()
    migrate(path, tmp_path / 'five.db', target_version=6)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT * FROM security_audit_events').fetchall() == events
        assert db.execute('SELECT * FROM security_audit_delivery').fetchall() == deliveries
        assert db.execute('SELECT destination_id,scope_kind,scope_id,generation,state FROM security_audit_destinations').fetchall() == [('removed-sink', 'account', 'user', 1, 'unconfigured')]
        claim = "UPDATE security_audit_delivery SET state='leased',attempt=attempt+1,lease_owner=?,lease_expires_at=120"
        with pytest.raises(sqlite3.IntegrityError, match='audit_destination_not_active'):
            db.execute(claim, ('c' * 32,))
        for statement in (
            'DELETE FROM security_audit_destinations',
            'INSERT OR REPLACE INTO security_audit_destinations SELECT * FROM security_audit_destinations',
            "UPDATE security_audit_destinations SET state='active'",
            "UPDATE security_audit_destinations SET scope_id='other',generation=2",
            "UPDATE security_audit_destinations SET state='blocked',generation=2",
            "UPDATE security_audit_destinations SET state='retired',generation=2",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(statement)
        db.execute("UPDATE security_audit_destinations SET state='active',generation=2")
        for destination, scope in (('unknown-sink', 'user'), ('removed-sink', 'other')):
            event = ('d' if scope == 'user' else 'e') * 32
            db.execute("INSERT INTO security_audit_events(event_id,schema_version,event_kind,occurred_at,actor_kind,actor_id,scope_kind,scope_id,affected_count) VALUES (?,1,'console.account_sessions.revoked',100,'user',?,'account',?,1)", (event, scope, scope))
            with pytest.raises(sqlite3.IntegrityError, match='audit_destination_not_active'):
                db.execute("INSERT INTO security_audit_delivery(event_id,destination_id,state,next_attempt_at) VALUES (?,?,'pending',100)", (event, destination))
        db.execute(claim, ('c' * 32,))
        db.execute("UPDATE security_audit_destinations SET state='paused',generation=3")
        # Already admitted acknowledgement remains possible after suspension.
        db.execute("UPDATE security_audit_delivery SET state='delivered',lease_owner=NULL,lease_expires_at=NULL,delivered_at=110")
        db.execute("UPDATE security_audit_destinations SET state='retired',required_through_sequence=2,generation=4")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE security_audit_destinations SET state='active',required_through_sequence=NULL,generation=5")


def test_conflicting_historical_scopes_reject_without_change(legacy, tmp_path):
    path, baseline = legacy
    migrate(path, baseline, target_version=5)
    history(path, conflict=True)
    before = dump(path)
    backup = tmp_path / 'conflict.db'
    with pytest.raises(MigrationError, match='migration_failed'):
        migrate(path, backup, target_version=6)
    assert verify(path) == 5 and dump(path) == before
    assert verify_backup(backup, expected_version=5) and dump(backup) == before


def test_late_failure_rolls_back_registry_and_journal(legacy, tmp_path, monkeypatch):
    from app.migrations import audit_governance_v6
    path, baseline = legacy
    migrate(path, baseline, target_version=5)
    history(path)
    before = dump(path)
    original = audit_governance_v6.apply
    def fail(db):
        original(db)
        raise sqlite3.OperationalError('injected_late_failure')
    monkeypatch.setattr(audit_governance_v6, 'apply', fail)
    with pytest.raises(MigrationError):
        migrate(path, tmp_path / 'late.db', target_version=6)
    assert verify(path) == 5 and dump(path) == before
    assert verify_backup(tmp_path / 'late.db', expected_version=5)


def test_actual_process_exit_before_commit_and_retry(legacy, tmp_path):
    path, baseline = legacy
    migrate(path, baseline, target_version=5)
    history(path)
    before = dump(path)
    code = '''
import os,sys
from pathlib import Path
from app.migrations import migrate,audit_governance_v6
original=audit_governance_v6.apply
def crash(db):
    original(db)
    os._exit(73)
audit_governance_v6.apply=crash
migrate(Path(sys.argv[1]),Path(sys.argv[2]),target_version=6)
'''
    backup = tmp_path / 'crash.db'
    result = subprocess.run([sys.executable, '-c', code, str(path), str(backup)],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=15)
    assert result.returncode == 73, result.stderr.decode()
    assert verify(path) == 5 and dump(path) == before
    assert verify_backup(backup, expected_version=5)
    assert migrate(path, tmp_path / 'retry.db', target_version=6).applied
    assert verify(path) == 6


def test_existing_delivery_consumer_refuses_offline_only_schema(legacy, tmp_path):
    from app.audit_delivery import AuditDeliveryError, AuditDeliveryRepository
    path, baseline = legacy
    migrate(path, baseline, target_version=5)
    history(path)
    migrate(path, tmp_path / 'five.db', target_version=6)
    before = dump(path)
    with pytest.raises(AuditDeliveryError, match='audit_schema_required'):
        AuditDeliveryRepository(path, destination_id='removed-sink', scope_kind='account', scope_id='user')
    assert dump(path) == before
