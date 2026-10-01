from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from app.audit_delivery import AuditDeliveryRepository, AuditDeliveryError
from test_audit_repository import reader, audited_release, release, ledger, legacy


@pytest.fixture
def outbox(reader):
    path, _, access, source, _ = reader
    for _ in range(4):
        access.create_console_session(user_id='user', lifetime_seconds=60)
    return path, AuditDeliveryRepository(path, destination_id='sink', scope_kind='account', scope_id='user')


def test_bounded_enrollment_retry_ack_and_unchanged_ledger(outbox, monkeypatch):
    path, repo = outbox
    with sqlite3.connect(path) as db:
        before = db.execute('SELECT * FROM security_audit_events').fetchall()
    assert repo.enroll(limit=2, max_outstanding=3) == {'added': 2, 'remaining': True, 'capacity_reached': False}
    assert repo.enroll(limit=2, max_outstanding=3) == {'added': 1, 'remaining': True, 'capacity_reached': True}
    assert repo.enroll(limit=2, max_outstanding=3)['added'] == 0
    lease = repo.claim(limit=2, lease_seconds=10)
    assert len(lease.events) == 2 and lease.expires_at == 110
    ids = [row['event_id'] for row in lease.events]
    repo.retry(event_ids=ids, lease_owner=lease.owner)
    assert len(repo.claim(limit=100).events) == 1
    monkeypatch.setattr('app.audit_delivery.time.time', lambda: 102)
    again = repo.claim(limit=2)
    assert [row['event_id'] for row in again.events] == ids and again.owner != lease.owner
    repo.acknowledge(event_ids=ids, lease_owner=again.owner)
    with pytest.raises(AuditDeliveryError, match='lease_conflict'):
        repo.acknowledge(event_ids=ids, lease_owner=again.owner)
    assert repo.enroll(limit=100, max_outstanding=3)['added'] == 2
    status = repo.status()
    assert status['delivered'] == 2 and status['pending'] == 2 and status['leased'] == 1
    assert status['last_ack_at'] == 102 and status['oldest_unacked_at'] == 100
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT * FROM security_audit_events').fetchall() == before


def test_expiry_reopen_and_stale_mixed_ack_rollback(outbox, monkeypatch):
    path, repo = outbox
    repo.enroll()
    first = repo.claim(limit=2, lease_seconds=5)
    ids = [row['event_id'] for row in first.events]
    monkeypatch.setattr('app.audit_delivery.time.time', lambda: 105)
    assert repo.status()['expired_leases'] == 2
    with pytest.raises(AuditDeliveryError, match='lease_conflict'):
        repo.acknowledge(event_ids=ids, lease_owner=first.owner)
    reopened = AuditDeliveryRepository(path, destination_id='sink', scope_kind='account', scope_id='user')
    second = reopened.claim(limit=2)
    assert second.owner != first.owner and second.events == first.events
    with pytest.raises(AuditDeliveryError, match='lease_conflict'):
        repo.acknowledge(event_ids=ids, lease_owner=first.owner)
    with pytest.raises(AuditDeliveryError, match='lease_conflict'):
        repo.acknowledge(event_ids=ids+['f'*32], lease_owner=second.owner)
    assert repo.status()['delivered'] == 0
    reopened.acknowledge(event_ids=ids, lease_owner=second.owner)
    assert repo.status()['delivered'] == 2


def test_concurrent_claims_are_disjoint_and_enrollment_idempotent(outbox):
    _, repo = outbox
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: repo.enroll(), range(2)))
    assert sum(result['added'] for result in results) == 5
    with ThreadPoolExecutor(max_workers=2) as pool:
        leases = list(pool.map(lambda _: repo.claim(limit=3), range(2)))
    ids = [event['event_id'] for lease in leases for event in lease.events]
    assert len(ids) == len(set(ids)) == 5


def test_destination_scope_cannot_be_rebound(outbox):
    path, repo = outbox
    repo.enroll()
    foreign = AuditDeliveryRepository(path, destination_id='sink', scope_kind='account', scope_id='other')
    for call in [foreign.enroll, foreign.claim, foreign.status]:
        with pytest.raises(AuditDeliveryError, match='destination_scope_conflict'):
            call()


def test_payload_bounds_and_invalid_batch_do_not_advance(outbox):
    path, repo = outbox
    repo.enroll()
    with pytest.raises(AuditDeliveryError, match='payload_capacity'):
        repo.claim(max_bytes=2)
    assert repo.status()['pending'] == 5
    one = repo.claim(limit=1)
    event_id = one.events[0]['event_id']
    with pytest.raises(AuditDeliveryError, match='invalid_delivery_batch'):
        repo.acknowledge(event_ids=[event_id, event_id], lease_owner=one.owner)
    assert repo.status()['delivered'] == 0
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT sum(attempt) FROM security_audit_delivery').fetchone() == (1,)


@pytest.mark.parametrize('options', [{'limit': 0}, {'limit': True}, {'limit': 101},
    {'lease_seconds': 0}, {'lease_seconds': 301}, {'max_bytes': 0}, {'max_bytes': 262145}])
def test_claim_bounds(outbox, options):
    _, repo = outbox
    with pytest.raises(AuditDeliveryError):
        repo.claim(**options)


def test_late_update_failure_rolls_back_whole_batch(outbox):
    path, repo = outbox
    repo.enroll()
    lease = repo.claim(limit=2)
    ids = [event['event_id'] for event in lease.events]
    original = repo._transaction
    from contextlib import contextmanager
    @contextmanager
    def fault():
        with original() as db:
            yield db
            raise RuntimeError('injected_before_commit')
    repo._transaction = fault
    with pytest.raises(RuntimeError, match='injected'):
        repo.acknowledge(event_ids=ids, lease_owner=lease.owner)
    repo._transaction = original
    assert repo.status()['delivered'] == 0 and repo.status()['leased'] == 2
    repo.acknowledge(event_ids=ids, lease_owner=lease.owner)
    assert repo.status()['delivered'] == 2


@pytest.mark.parametrize('operation', ['enroll', 'claim', 'acknowledge', 'retry'])
@pytest.mark.parametrize('phase', ['before', 'after'])
def test_process_exit_preserves_atomic_delivery_state(outbox, operation, phase, monkeypatch):
    import json
    from pathlib import Path
    import subprocess
    import sys
    from app.migrations import verify
    path, repo = outbox
    args = {}
    if operation != 'enroll':
        repo.enroll()
    if operation in ('acknowledge', 'retry'):
        lease = repo.claim(limit=2, lease_seconds=5)
        args = {'event_ids': [event['event_id'] for event in lease.events], 'lease_owner': lease.owner}
    def snapshot():
        with sqlite3.connect(path) as db:
            return db.execute('SELECT * FROM security_audit_delivery ORDER BY event_id').fetchall()
    before = snapshot()
    child = r'''
import json,os,sys
from contextlib import contextmanager
from app.audit_delivery import AuditDeliveryRepository
import app.audit_delivery as module
module.time.time=lambda:100
p=json.loads(sys.stdin.buffer.read())
repo=AuditDeliveryRepository(p['path'],destination_id='sink',scope_kind='account',scope_id='user')
original=repo._transaction
@contextmanager
def crash():
    with original() as db:
        yield db
        if p['phase']=='before':os._exit(71)
    os._exit(72)
repo._transaction=crash
getattr(repo,p['operation'])(**p['args'])
raise AssertionError('exit hook not reached')
'''
    result = subprocess.run([sys.executable, '-c', child], input=json.dumps({
        'path': str(path), 'operation': operation, 'phase': phase, 'args': args}).encode(),
        capture_output=True, cwd=Path(__file__).resolve().parents[1], timeout=15)
    assert result.returncode == (71 if phase == 'before' else 72)
    assert not result.stdout and not result.stderr
    assert verify(path) == 5
    if phase == 'before':
        assert snapshot() == before
    else:
        assert snapshot() != before
        status = repo.status()
        if operation == 'enroll':
            assert status['pending'] == 5
        elif operation == 'claim':
            assert status['leased'] == 5
            monkeypatch.setattr('app.audit_delivery.time.time', lambda: 130)
            assert len(repo.claim().events) == 5
        elif operation == 'acknowledge':
            assert status['delivered'] == 2
        else:
            assert status['pending'] == 5 and status['leased'] == 0
            assert len(repo.claim().events) == 3  # Retried two remain in backoff.
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA integrity_check').fetchall() == [('ok',)]


def test_exact_payload_cutoff_and_backoff_cap(outbox, monkeypatch):
    import json
    _, repo = outbox
    repo.enroll()
    first = repo.claim(limit=1)
    event_id = first.events[0]['event_id']
    # Release and wait out first retry before selecting by the exact serialized byte size.
    repo.retry(event_ids=[event_id], lease_owner=first.owner)
    now = 102
    monkeypatch.setattr('app.audit_delivery.time.time', lambda: now)
    size = len(json.dumps(list(first.events), ensure_ascii=True, separators=(',', ':')).encode())
    one = repo.claim(max_bytes=size)
    assert one.events == first.events
    for attempt in range(2, 12):
        repo.retry(event_ids=[event_id], lease_owner=one.owner)
        with sqlite3.connect(repo.path) as db:
            due = db.execute('SELECT next_attempt_at FROM security_audit_delivery WHERE event_id=?', (event_id,)).fetchone()[0]
        assert due-now == min(300, 2**attempt)
        now = due
        one = repo.claim(limit=1)
        assert one.events == first.events


def test_schema_drift_blocks_all_state_changes(outbox):
    path, repo = outbox
    repo.enroll()
    with sqlite3.connect(path) as db:
        before = db.execute('SELECT * FROM security_audit_delivery').fetchall()
        db.execute('DROP INDEX security_audit_delivery_due')
    with pytest.raises(AuditDeliveryError, match='unavailable'):
        repo.claim()
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT * FROM security_audit_delivery').fetchall() == before
