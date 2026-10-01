import asyncio
import json
import logging
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from app.audit_delivery import AuditDeliveryRepository
from app.audit_exporter import AuditExporter
from app.audit_sender import AuditSendError
from app.audit_status import collect_status
from test_audit_service import ENTRY, settings
from test_audit_repository import reader, audited_release, release, ledger, legacy


def configured(path):
    return settings(db_path=path, audit_export_config=json.dumps([ENTRY]))


def test_status_counts_unenrolled_backlog_in_read_only_snapshot(reader):
    path, _, access, _, _ = reader
    access.create_console_session(user_id='user', lifetime_seconds=60)
    config = configured(path)
    target = config.audit_destinations[0]
    repo = AuditDeliveryRepository(path, destination_id=target.destination_id, scope_kind='account', scope_id='user')
    with sqlite3.connect(path) as db: before = list(db.iterdump())
    initial = collect_status(config)['destinations'][0]
    assert initial['unenrolled'] == initial['backlog'] == 2
    assert initial['pending'] == initial['leased'] == initial['delivered'] == 0
    assert initial['oldest_unacked_at'] == initial['oldest_unenrolled_at'] == 100
    assert initial['last_ack_at'] is None
    with sqlite3.connect(path) as db: assert list(db.iterdump()) == before
    repo.enroll(limit=1)
    lease = repo.claim()
    mid = collect_status(config)['destinations'][0]
    assert mid['leased'] == mid['unenrolled'] == 1 and mid['backlog'] == 2
    repo.acknowledge(event_ids=[event['event_id'] for event in lease.events], lease_owner=lease.owner)
    last = collect_status(config)['destinations'][0]
    assert last['delivered'] == last['unenrolled'] == last['backlog'] == 1
    assert last['last_ack_at'] == 100 and last['oldest_unacked_at'] == 100
    serialized = json.dumps(collect_status(config))
    assert ENTRY['token'] not in serialized and ENTRY['host'] not in serialized


def test_storage_failure_is_not_reported_as_empty_success(reader):
    path, _, _, _, _ = reader
    with sqlite3.connect(path) as db: db.execute('DROP INDEX security_audit_delivery_due')
    report = collect_status(configured(path))
    assert report['ok'] is False
    assert report['destinations'][0]['error'] == 'audit_status_unavailable'
    assert 'backlog' not in report['destinations'][0]


def test_status_does_not_reserve_writer_lock(reader):
    path, _, _, _, _ = reader
    config = configured(path)
    with sqlite3.connect(path, isolation_level=None) as writer:
        writer.execute('BEGIN IMMEDIATE')
        try:
            report = collect_status(config)
            assert report['ok'] and report['destinations'][0]['unenrolled'] == 1
        finally:
            writer.rollback()


@pytest.mark.parametrize('case', ['pending', 'drained', 'disabled', 'malformed', 'drift'])
def test_actual_operator_cli_exit_codes_and_redaction(reader, case):
    path, _, _, _, _ = reader
    if case == 'drained':
        target = configured(path).audit_destinations[0]
        repo = AuditDeliveryRepository(path, destination_id=target.destination_id, scope_kind='account', scope_id='user')
        repo.enroll()
        lease = repo.claim()
        repo.acknowledge(event_ids=[event['event_id'] for event in lease.events], lease_owner=lease.owner)
    if case == 'drift':
        with sqlite3.connect(path) as db: db.execute('DROP INDEX security_audit_delivery_due')
    environment = os.environ.copy()
    environment.update(ATOM_DB_PATH=str(path), ATOM_ENVIRONMENT='test', ATOM_SANDBOX_MODE='local',
                       ATOM_SESSION_MODE='durable', ATOM_COOKIE_SECURE='true', ATOM_COOKIE_PATH='/',
                       ATOM_CONSOLE_ORIGIN='https://console.example.org',
                       ATOM_AUDIT_EXPORT_CONFIG='[]' if case == 'disabled' else
                       '{'+ENTRY['token'] if case == 'malformed' else json.dumps([ENTRY]))
    result = subprocess.run([sys.executable, '-m', 'app.audit_status', '--require-drained'],
        cwd=Path(__file__).resolve().parents[1], env=environment, capture_output=True, timeout=15)
    assert result.returncode == {'pending': 2, 'drained': 0, 'disabled': 2, 'malformed': 1, 'drift': 1}[case]
    report = json.loads(result.stdout)
    assert report['ok'] is (case not in ('malformed', 'drift'))
    assert not result.stderr
    assert ENTRY['token'].encode() not in result.stdout
    assert ENTRY['host'].encode() not in result.stdout


def test_state_logs_are_redacted_deduplicated_and_recovery_is_explicit(reader, monkeypatch, caplog):
    path, _, _, _, _ = reader
    target = configured(path).audit_destinations[0]
    attempts = []
    async def send(*args, **kwargs):
        attempts.append(1)
        if len(attempts) < 3:
            raise AuditSendError(target.token)  # Hostile error detail must never be logged.
    monkeypatch.setattr('app.audit_exporter.send_audit_events', send)
    caplog.set_level(logging.INFO, logger='app.audit_exporter')
    async def scenario():
        exporter = AuditExporter(path, target)
        try:
            assert (await exporter.run_once()).outcome == 'retry'
            monkeypatch.setattr('app.audit_delivery.time.time', lambda: 102)
            assert (await exporter.run_once()).outcome == 'retry'
            monkeypatch.setattr('app.audit_delivery.time.time', lambda: 106)
            assert (await exporter.run_once()).outcome == 'delivered'
        finally:
            await exporter.close()
    asyncio.run(scenario())
    messages = [json.loads(record.message) for record in caplog.records if record.name == 'app.audit_exporter']
    assert [message['code'] for message in messages] == ['audit_export_retry_pending', 'audit_export_recovered']
    assert all(set(message) == {'event', 'destination_id', 'code'} for message in messages)
    assert target.token not in caplog.text and target.host not in caplog.text


def test_broken_log_sink_does_not_undo_delivery(reader, monkeypatch):
    path, _, _, _, _ = reader
    target = configured(path).audit_destinations[0]
    attempts = []
    async def send(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1: raise AuditSendError('injected_retry')
    def broken(*args, **kwargs): raise OSError('diagnostic_sink_failed')
    monkeypatch.setattr('app.audit_exporter.send_audit_events', send)
    monkeypatch.setattr('app.audit_exporter._LOG.log', broken)
    async def scenario():
        exporter = AuditExporter(path, target)
        try:
            assert (await exporter.run_once()).outcome == 'retry'
            monkeypatch.setattr('app.audit_delivery.time.time', lambda: 102)
            assert (await exporter.run_once()).outcome == 'delivered'
            assert exporter.diagnostic_failures == 2 and exporter.last_error is None
        finally:
            await exporter.close()
    asyncio.run(scenario())
