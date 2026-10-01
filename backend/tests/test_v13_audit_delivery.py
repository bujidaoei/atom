"""Version-13 destination registration and real console-event delivery."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from app.access_repository import AccessRepository
from app.audit_delivery import AuditDeliveryError, AuditDeliveryRepository
from app.audit_governance import AuditGovernanceRepository
from app.migrations import migrate, verify
from test_revision_migrations import legacy


@pytest.fixture
def delivery(legacy, tmp_path, monkeypatch):
    path, backup = legacy
    migrate(path, backup, target_version=11)
    migrate(path, tmp_path / 'before-v12.db', target_version=12)
    migrate(path, tmp_path / 'before-v13.db', target_version=13)
    for module in ('access_repository', 'audit_governance', 'audit_delivery'):
        monkeypatch.setattr('app.' + module + '.time.time', lambda: 100)
    access = AccessRepository(path)
    for _ in range(5):
        access.create_console_session(user_id='user', lifetime_seconds=60)
    AuditGovernanceRepository(path).execute(command_id='register', operator_id='operator',
        destination_id='sink', scope_kind='account', scope_id='user',
        action='register', expected_generation=0)
    return path, AuditDeliveryRepository(path, destination_id='sink',
        scope_kind='account', scope_id='user')


def test_v13_concurrent_claim_retry_ack_and_destination_fence(delivery, monkeypatch):
    path, repo = delivery
    with sqlite3.connect(path) as db:
        original = db.execute('SELECT event_id FROM security_audit_events ORDER BY sequence').fetchall()
    assert len(original) == 5 and verify(path) == 13
    assert repo.enroll(limit=5)['added'] == 5
    with ThreadPoolExecutor(max_workers=2) as pool:
        leases = list(pool.map(lambda _: repo.claim(limit=2, lease_seconds=10), range(2)))
    assert all(len(lease.events) == 2 for lease in leases)
    identities = [event['event_id'] for lease in leases for event in lease.events]
    assert len(set(identities)) == 4
    retry_ids = [event['event_id'] for event in leases[0].events]
    ack_ids = [event['event_id'] for event in leases[1].events]
    repo.retry(event_ids=retry_ids, lease_owner=leases[0].owner)
    repo.acknowledge(event_ids=ack_ids, lease_owner=leases[1].owner)
    with pytest.raises(AuditDeliveryError, match='lease_conflict'):
        repo.acknowledge(event_ids=retry_ids, lease_owner=leases[0].owner)
    monkeypatch.setattr('app.audit_delivery.time.time', lambda: 102)
    remainder = repo.claim(limit=3)
    assert len(remainder.events) == 3
    assert set(event['event_id'] for event in remainder.events) == set(retry_ids) | (
        {row[0] for row in original} - set(identities))
    repo.acknowledge(event_ids=[event['event_id'] for event in remainder.events],
        lease_owner=remainder.owner)
    assert repo.status()['delivered'] == 5
    foreign = AuditDeliveryRepository(path, destination_id='sink',
        scope_kind='account', scope_id='other')
    with pytest.raises(AuditDeliveryError, match='destination_scope_conflict'):
        foreign.status()
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT event_id FROM security_audit_events ORDER BY sequence').fetchall() == original
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []


@pytest.mark.parametrize('phase', ['before', 'after'])
def test_v13_ack_process_exit_has_one_atomic_outcome(delivery, phase):
    path, repo = delivery
    repo.enroll()
    lease = repo.claim(limit=2)
    event_ids = [event['event_id'] for event in lease.events]
    script = r'''
import json, os, sys
from contextlib import contextmanager
from app.audit_delivery import AuditDeliveryRepository
import app.audit_delivery as module
module.time.time = lambda: 100
args = json.loads(sys.stdin.buffer.read())
repo = AuditDeliveryRepository(args['path'], destination_id='sink',
    scope_kind='account', scope_id='user')
original = repo._transaction
@contextmanager
def crash():
    with original() as db:
        yield db
        if args['phase'] == 'before': os._exit(71)
    os._exit(72)
repo._transaction = crash
repo.acknowledge(event_ids=args['event_ids'], lease_owner=args['owner'])
'''
    result = subprocess.run([sys.executable, '-c', script], input=json.dumps({
        'path': str(path), 'phase': phase, 'event_ids': event_ids,
        'owner': lease.owner}).encode(), capture_output=True,
        cwd=Path(__file__).resolve().parents[1], timeout=15)
    assert result.returncode == (71 if phase == 'before' else 72), result.stderr.decode()
    assert not result.stdout and not result.stderr
    assert verify(path) == 13
    reopened = AuditDeliveryRepository(path, destination_id='sink',
        scope_kind='account', scope_id='user')
    assert reopened.status()['delivered'] == (0 if phase == 'before' else 2)
    if phase == 'before':
        reopened.acknowledge(event_ids=event_ids, lease_owner=lease.owner)
        assert reopened.status()['delivered'] == 2
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
