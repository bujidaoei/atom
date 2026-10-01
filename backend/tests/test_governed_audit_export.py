import asyncio
import sqlite3

import pytest

from app.audit_delivery import AuditDeliveryRepository, AuditDeliveryError
from app.audit_exporter import AuditExporter
from app.audit_governance import AuditGovernanceRepository
from app.audit_sender import AuditSendError
from app.migrations import migrate
from test_audit_destination import destination
from test_audit_repository import reader, audited_release, release, ledger, legacy


@pytest.fixture(params=[7,9])
def governed(reader, tmp_path, request):
    path, *_ = reader
    target = destination()
    migrate(path, tmp_path/'before-seven.db', target_version=request.param)
    governance = AuditGovernanceRepository(path)
    def change(action, generation, command_id, **extra):
        return governance.execute(command_id=command_id, operator_id='operator', destination_id=target.destination_id,
            scope_kind=target.scope_kind, scope_id=target.scope_id, action=action, expected_generation=generation, **extra)
    change('register', 0, 'register')
    repository = AuditDeliveryRepository(path, destination_id=target.destination_id, scope_kind='account', scope_id='user')
    return path, target, repository, governance, change


def test_pause_blocks_new_claims_but_preserves_inflight_settlement(governed):
    _, _, repo, _, change = governed
    repo.enroll()
    lease = repo.claim()
    assert lease.generation == 1
    change('suspend', 1, 'pause')
    for operation in (repo.enroll, repo.claim):
        with pytest.raises(AuditDeliveryError, match='inactive'):
            operation()
    repo.acknowledge(event_ids=[event['event_id'] for event in lease.events], lease_owner=lease.owner)
    assert repo.status()['delivered'] == 1 and repo.status()['registry_state'] == 'paused'
    change('retire', 2, 'retire')
    assert repo.status()['backlog'] == 0


def test_permanent_failure_survives_restart_and_requires_explicit_resume(governed, monkeypatch):
    path, target, repo, registry, change = governed
    calls = []
    async def sender(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise AuditSendError('untrusted-remote-message', retryable=False)
    monkeypatch.setattr('app.audit_exporter.send_audit_events', sender)
    async def scenario():
        first = AuditExporter(path, target)
        try:
            assert (await first.run_once()).outcome == 'blocked'
        finally:
            await first.close()
        assert registry.page()[0]['state'] == 'blocked'
        second = AuditExporter(path, target)
        try:
            await second.prepare()
            assert (await second.run_once()).outcome == 'suspended'
            assert calls == [1] and repo.status()['leased'] == 1
            change('resume', 2, 'resume')
            monkeypatch.setattr('app.audit_delivery.time.time', lambda: 161)
            assert (await second.run_once()).outcome == 'delivered'
            assert repo.status()['delivered'] == 1 and second.last_error is None
        finally:
            await second.close()
    asyncio.run(scenario())
    with sqlite3.connect(path) as db:
        assert 'untrusted-remote-message' not in '\n'.join(db.iterdump())
        assert db.execute("SELECT count(*) FROM security_audit_destination_commands WHERE action='block'").fetchone() == (1,)


@pytest.mark.parametrize('outcome', ['success', 'failure'])
def test_admin_change_during_send_keeps_new_generation(governed, monkeypatch, outcome):
    path, target, repo, registry, change = governed
    async def sender(*args, **kwargs):
        change('suspend', 1, 'pause')
        change('resume', 2, 'resume')
        if outcome == 'failure':
            raise AuditSendError('rejected', retryable=False)
    monkeypatch.setattr('app.audit_exporter.send_audit_events', sender)
    async def scenario():
        exporter = AuditExporter(path, target)
        try:
            result = await exporter.run_once()
            assert result.outcome == ('delivered' if outcome == 'success' else 'superseded')
            assert registry.page()[0]['generation'] == 3 and registry.page()[0]['state'] == 'active'
            assert repo.status()['delivered'] == int(outcome == 'success')
        finally:
            await exporter.close()
    asyncio.run(scenario())


def test_unregistered_scope_and_retired_watermark(governed):
    path, target, repo, _, change = governed
    unknown = AuditDeliveryRepository(path, destination_id='missing', scope_kind='account', scope_id='user')
    with pytest.raises(AuditDeliveryError, match='unregistered'):
        unknown.status()
    wrong = AuditDeliveryRepository(path, destination_id=target.destination_id, scope_kind='account', scope_id='other')
    with pytest.raises(AuditDeliveryError, match='scope_conflict'):
        wrong.status()
    repo.enroll()
    lease = repo.claim()
    repo.acknowledge(event_ids=[event['event_id'] for event in lease.events], lease_owner=lease.owner)
    retired = change('retire', 1, 'retire')
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO security_audit_events(event_id,schema_version,event_kind,occurred_at,actor_kind,actor_id,scope_kind,scope_id,affected_count) VALUES (?,1,'console.account_sessions.revoked',162,'user','user','account','user',1)", ('f'*32,))
    state = repo.status()
    assert state['required_through_sequence'] == retired.required_through_sequence
    assert state['backlog'] == state['unenrolled'] == 0
