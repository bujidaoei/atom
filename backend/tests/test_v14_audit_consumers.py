"""Real audit rows remain readable and deliverable after the offline v14 migration."""
import os
import sqlite3

import pytest

from app.audit_delivery import AuditDeliveryRepository
from app.audit_archiving import AuditArchiving
from app.audit_governance import AuditGovernanceRepository
from app.audit_repository import AuditRepository
from app.audit_retention import RetentionRepository
from app.migrations import migrate, verify
from test_audit_retention import args
from test_revision_migrations import legacy
from test_v13_audit_delivery import delivery


@pytest.fixture
def migrated(delivery, tmp_path):
    path, _ = delivery
    migrate(path, tmp_path / 'before-v14.db', target_version=14)
    assert verify(path) == 14
    return path


def test_v14_audit_read_delivery_retention_and_archive(migrated, monkeypatch, tmp_path):
    path = migrated
    monkeypatch.setattr('app.audit_repository.time.time', lambda: 100)
    monkeypatch.setattr('app.audit_delivery.time.time', lambda: 100)
    monkeypatch.setattr('app.audit_retention.time.time', lambda: 102)
    with sqlite3.connect(path) as db:
        session = db.execute('SELECT id FROM console_sessions WHERE user_id=? LIMIT 1',
                             ('user',)).fetchone()[0]
    page = AuditRepository(path).page(user_id='user', source_session_id=session)
    assert len(page.events) == 5 and page.archived == ()

    governance = AuditGovernanceRepository(path)
    assert governance.execute(command_id='register', operator_id='operator',
        destination_id='sink', scope_kind='account', scope_id='user',
        action='register', expected_generation=0).generation == 1
    destination = AuditDeliveryRepository(path, destination_id='sink',
        scope_kind='account', scope_id='user')
    retention = RetentionRepository(path)
    assert retention.execute(**args(state='active', min_age_seconds=1)).generation == 1
    assert retention.plan(policy_id='policy', expected_generation=1)['blocked_count'] == 5
    assert destination.enroll()['added'] == 5
    lease = destination.claim(limit=5)
    assert len(lease.events) == 5
    destination.acknowledge(event_ids=[event['event_id'] for event in lease.events],
                            lease_owner=lease.owner)
    assert destination.status()['delivered'] == 5
    eligible = retention.plan(policy_id='policy', expected_generation=1)
    assert eligible['candidate_count'] == 5 and eligible['blocked_count'] == 0
    if os.name != 'nt':
        archive_root = tmp_path / 'archive'
        archive_root.mkdir(mode=0o700)
        archiving = AuditArchiving(path, store_id='archive', root=archive_root)
        archived = archiving.archive(archive_id='archived-v14', operator_id='operator',
                                    policy_id='policy', expected_generation=1)
        assert archived['event_count'] == 5
        assert archiving.inspect(archive_id='archived-v14')['last_sequence'] == page.upper
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
