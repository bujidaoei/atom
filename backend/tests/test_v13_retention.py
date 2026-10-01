"""v13 policy and hold decisions stay distinct from archive and deletion authority."""
import sqlite3

import pytest

from app.audit_pruning import AuditPruning
from app.audit_retention import RetentionError, RetentionRepository
from app.migrations import verify
from test_audit_retention import args
from test_revision_migrations import legacy
from test_v13_audit_delivery import delivery


def test_v13_actual_events_require_delivery_then_obey_hold_without_prune(
        delivery, tmp_path, monkeypatch):
    path, destination = delivery
    assert verify(path) == 13
    retention = RetentionRepository(path)
    created = retention.execute(**args(state='active', min_age_seconds=1))
    assert created.generation == 1
    before = retention.plan(policy_id='policy', expected_generation=1)
    assert before['candidate_count'] == 0 and before['blocked_count'] == 5
    assert all('unconfirmed_delivery' in item['blocked_reasons'] for item in before['items'])
    destination.enroll()
    lease = destination.claim(limit=5)
    assert len(lease.events) == 5
    destination.acknowledge(event_ids=[event['event_id'] for event in lease.events],
        lease_owner=lease.owner)
    monkeypatch.setattr('app.audit_retention.time.time', lambda: 102)
    with sqlite3.connect(path) as db:
        snapshot = list(db.iterdump())
    eligible = retention.plan(policy_id='policy', expected_generation=1)
    assert eligible['candidate_count'] == 5 and eligible['blocked_count'] == 0, [
        item['blocked_reasons'] for item in eligible['items']]
    assert not eligible['deletion_authorized']
    with sqlite3.connect(path) as db:
        assert list(db.iterdump()) == snapshot
    retention.execute(**args('place_hold', 1, 'legal', hold_id='legal', hold_kind='legal'))
    held = retention.plan(policy_id='policy', expected_generation=2)
    assert held['candidate_count'] == 0 and held['blocked_count'] == 5
    assert all('active_hold' in item['blocked_reasons'] for item in held['items'])
    with pytest.raises(RetentionError, match='retention_schema_required'):
        AuditPruning(path, store_id='archive', root=tmp_path / 'archive-store',
            verifier_id='verifier', expected_image='sha256:' + 'a' * 64,
            expected_policy_digest='b' * 64)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM security_audit_prune_receipts').fetchone() == (0,)
        assert db.execute('SELECT count(*) FROM security_audit_archived_events').fetchone() == (0,)
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
