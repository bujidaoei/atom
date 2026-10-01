import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from app.access_repository import AccessRepository
from app.audit_delivery import AuditDeliveryRepository
from app.audit_governance import AuditGovernanceError, AuditGovernanceRepository
from app.migrations import migrate
from test_governed_audit_export import governed, reader, audited_release, release, ledger, legacy


def delivery(path, identity):
    return AuditDeliveryRepository(path, destination_id=identity, scope_kind='account', scope_id='user')


def settle(repo):
    repo.enroll()
    lease = repo.claim()
    repo.acknowledge(event_ids=[event['event_id'] for event in lease.events], lease_owner=lease.owner)


def test_off_page_history_prevents_false_global_drain(governed):
    path, target, repo, registry, change = governed
    registry.execute(command_id='other', operator_id='operator', destination_id='000', scope_kind='account',
        scope_id='user', action='register', expected_generation=0)
    settle(delivery(path, '000'))
    change('block', 1, 'block', reason='receiver_configuration')
    first = registry.obligations(limit=1)
    assert first['coverage'] == 'registered_destinations' and first['registry_count'] == 2
    assert first['destinations'][0]['destination_id'] == '000'
    assert first['destinations'][0]['backlog'] == 0
    assert first['next_after'] == '000' and not first['registered_drained']
    second = registry.obligations(after=first['next_after'], limit=1)
    assert second['destinations'][0]['destination_id'] == target.destination_id
    assert second['destinations'][0]['state'] == 'blocked'
    assert second['destinations'][0]['unenrolled'] == second['destinations'][0]['backlog'] == 1
    assert second['destinations'][0]['oldest_unacked_at'] == 100
    assert second['next_after'] is None and not second['registered_drained']
    assert not registry.obligations(after='zzzz')['registered_drained']


def test_lease_expiry_retirement_and_new_business_events(governed, monkeypatch):
    path, _, repo, registry, change = governed
    repo.enroll()
    lease = repo.claim(lease_seconds=5)
    change('suspend', 1, 'pause')
    state = registry.obligations()['destinations'][0]
    assert state['leased'] == 1 and state['expired_leases'] == 0
    monkeypatch.setattr('app.audit_governance.time.time', lambda: 105)
    assert registry.obligations()['destinations'][0]['expired_leases'] == 1
    change('resume', 2, 'resume')
    lease = repo.claim()
    repo.acknowledge(event_ids=[event['event_id'] for event in lease.events], lease_owner=lease.owner)
    change('retire', 3, 'retire')
    before = registry.obligations()
    assert before['registered_drained']
    AccessRepository(path).create_console_session(user_id='user', lifetime_seconds=60)
    after = registry.obligations()
    assert after['upper_sequence'] > before['upper_sequence']
    assert after['registered_drained'] and after['destinations'][0]['required_events'] == 1
    assert after['destinations'][0]['delivered'] == 1 and after['destinations'][0]['backlog'] == 0


def test_removed_config_migration_identity_is_visible(legacy, tmp_path):
    from test_audit_governance_migration import history
    path, backup = legacy
    migrate(path, backup, target_version=5)
    history(path)
    migrate(path, tmp_path/'before-seven.db', target_version=7)
    state = AuditGovernanceRepository(path).obligations()
    assert state['registry_count'] == 1 and not state['registered_drained']
    row = state['destinations'][0]
    assert row['destination_id'] == 'removed-sink' and row['state'] == 'unconfigured'
    assert row['pending'] == row['backlog'] == 2 and row['unenrolled'] == 0


def test_read_only_snapshot_coexists_with_writer_and_rejects_drift(governed):
    path, _, _, registry, _ = governed
    with sqlite3.connect(path) as db:
        before = list(db.iterdump())
        db.execute('BEGIN IMMEDIATE')
        assert registry.obligations()['destinations'][0]['backlog'] == 1
        assert list(db.iterdump()) == before
        db.rollback()
        db.execute('CREATE TABLE unexpected(id INTEGER)')
    with pytest.raises(AuditGovernanceError):
        registry.obligations()


@pytest.mark.parametrize('options', [dict(limit=0),dict(limit=101),dict(limit=True),dict(after='../sink'),dict(after=None)])
def test_invalid_page_bounds(governed, options):
    with pytest.raises(AuditGovernanceError, match='invalid_audit_governance_request'):
        governed[3].obligations(**options)


def test_actual_cli_drained_exit_covers_entire_registry(governed):
    path, _, repo, registry, _ = governed
    prefix = [sys.executable, '-m', 'app.audit_admin', '--database', str(path), 'status', '--require-drained', '--after', 'zzzz']
    def run(expected):
        result = subprocess.run(prefix, cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=15)
        assert result.returncode == expected and not result.stderr
        return json.loads(result.stdout)
    state = run(2)
    assert state['ok'] and state['destinations'] == [] and not state['registered_drained']
    settle(repo)
    assert run(0)['registered_drained']
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE unexpected(id INTEGER)')
    failure = run(1)
    assert not failure['ok'] and 'registered_drained' not in failure


def test_empty_registry_is_not_enabled_or_drained(legacy):
    path, backup = legacy
    migrate(path, backup, target_version=7)
    state = AuditGovernanceRepository(path).obligations()
    assert state['registry_count'] == 0 and not state['registered_drained']
    assert state['destinations'] == () and state['next_after'] is None


def test_concurrent_real_append_does_not_mix_snapshot_counts(governed, monkeypatch):
    path, _, repo, registry, _ = governed
    settle(repo)
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
    original = sqlite3.connect
    appended = []
    def connect(*args, **kwargs):
        db = original(*args, **kwargs)
        if '?mode=ro' in str(args[0]):
            def trace(sql):
                if sql == 'SELECT count(*) FROM security_audit_destinations' and not appended:
                    appended.append(True)
                    AccessRepository(path).create_console_session(user_id='user', lifetime_seconds=60)
            db.set_trace_callback(trace)
        return db
    with monkeypatch.context() as patch:
        patch.setattr('app.audit_governance.sqlite3.connect', connect)
        snapshot = registry.obligations()
    assert appended and snapshot['registered_drained']
    assert snapshot['destinations'][0]['required_events'] == snapshot['destinations'][0]['delivered'] == 1
    latest = registry.obligations()
    assert latest['upper_sequence'] > snapshot['upper_sequence']
    assert not latest['registered_drained'] and latest['destinations'][0]['backlog'] == 1
