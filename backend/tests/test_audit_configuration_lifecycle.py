"""Evidence for retained obligations when operator configuration changes."""
from dataclasses import replace
import json
import sqlite3

from app.audit_delivery import AuditDeliveryRepository
from app.audit_status import collect_status
from test_audit_service import ENTRY, settings
from test_audit_repository import reader, audited_release, release, ledger, legacy


def test_removed_destination_keeps_unconfirmed_history_and_reappears_on_restore(reader, monkeypatch):
    path, _, _, _, _ = reader
    configured = settings(db_path=path, audit_export_config=json.dumps([ENTRY]))
    target = configured.audit_destinations[0]
    repository = AuditDeliveryRepository(path, destination_id=target.destination_id,
                                        scope_kind=target.scope_kind, scope_id=target.scope_id)
    repository.enroll()
    first = repository.claim(lease_seconds=5)
    with sqlite3.connect(path) as db:
        before = list(db.iterdump())
    disabled = settings(db_path=path, audit_export_config='[]')
    report = collect_status(disabled)
    assert report['enabled'] is False and report['destinations'] == []
    with sqlite3.connect(path) as db:
        assert list(db.iterdump()) == before
    resumed = collect_status(configured)['destinations'][0]
    assert resumed['leased'] == resumed['backlog'] == 1 and resumed['delivered'] == 0
    monkeypatch.setattr('app.audit_delivery.time.time', lambda: 105)
    recovered = repository.claim()
    assert recovered.events == first.events and recovered.owner != first.owner


def test_new_receiver_ack_cannot_discharge_old_receiver_obligation(reader):
    path, _, _, _, _ = reader
    first_config = settings(db_path=path, audit_export_config=json.dumps([ENTRY]))
    first = first_config.audit_destinations[0]
    old = AuditDeliveryRepository(path, destination_id=first.destination_id,
                                  scope_kind=first.scope_kind, scope_id=first.scope_id)
    old.enroll()
    old.claim()
    new_config = settings(db_path=path, audit_export_config=json.dumps([ENTRY|{'path': '/new-collector'}]))
    second = new_config.audit_destinations[0]
    assert second.destination_id != first.destination_id
    new = AuditDeliveryRepository(path, destination_id=second.destination_id,
                                  scope_kind=second.scope_kind, scope_id=second.scope_id)
    new.enroll()
    lease = new.claim()
    new.acknowledge(event_ids=[event['event_id'] for event in lease.events], lease_owner=lease.owner)
    current_only = collect_status(new_config)['destinations'][0]
    assert current_only['backlog'] == 0 and current_only['delivered'] == 1
    assert old.status()['backlog'] == 1 and old.status()['delivered'] == 0
    rotated = replace(first, token='rotated-fixture-token-at-least-32-characters', addresses=('1.1.1.1',))
    assert rotated.destination_id == first.destination_id
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM security_audit_delivery').fetchone() == (2,)
        assert db.execute('SELECT count(*) FROM security_audit_events WHERE scope_kind=? AND scope_id=?',
                          ('account', 'user')).fetchone() == (1,)
