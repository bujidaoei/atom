import asyncio
import hashlib
import json
import sqlite3
import ssl
import threading

import pytest

from app.audit_delivery import AuditDeliveryRepository, AuditDeliveryError
from app.audit_exporter import AuditExporter, AuditExporterError
from app.audit_sender import AuditSendError
from test_audit_destination import certificate, destination
from test_audit_repository import reader, audited_release, release, ledger, legacy


def repository(path, target):
    return AuditDeliveryRepository(path, destination_id=target.destination_id,
                                   scope_kind=target.scope_kind, scope_id=target.scope_id)


@pytest.mark.parametrize('mode', ['success', 'retry', 'terminal', 'ack-failure'])
def test_cycle_only_acknowledges_confirmed_batch(reader, monkeypatch, mode):
    path, _, _, _, _ = reader
    target = destination()
    calls = []
    async def sender(_destination, events, **kwargs):
        calls.append(events)
        if mode in ('retry', 'terminal'):
            raise AuditSendError('fixture_failure', retryable=mode == 'retry')
    monkeypatch.setattr('app.audit_exporter.send_audit_events', sender)
    if mode == 'ack-failure':
        def fail(*args, **kwargs):
            raise AuditDeliveryError('fixture_ack_storage_failure')
        monkeypatch.setattr(AuditDeliveryRepository, 'acknowledge', fail)
    async def scenario():
        exporter = AuditExporter(path, target)
        try:
            if mode in ('terminal', 'ack-failure'):
                with pytest.raises(AuditExporterError): await exporter.run_once()
            else:
                result = await exporter.run_once()
                assert result.outcome == ('delivered' if mode == 'success' else 'retry')
                assert result.event_count == 1
                assert (await exporter.run_once()).outcome == 'idle'
            state = repository(path, target).status()
            assert state['delivered'] == (1 if mode == 'success' else 0)
            assert state['leased'] == (1 if mode in ('terminal', 'ack-failure') else 0)
            assert state['pending'] == (1 if mode == 'retry' else 0)
            if mode == 'terminal':
                with pytest.raises(AuditExporterError, match='not_admitted'): await exporter.run_once()
                assert exporter.last_error == 'audit_export_configuration'
            assert len(calls) == 1 and exporter.pending_count == 0
        finally:
            await exporter.close()
        with pytest.raises(AuditExporterError, match='not_admitted'): await exporter.run_once()
    asyncio.run(scenario())


@pytest.mark.parametrize('cancel_owned', [False, True])
def test_cancel_and_close_retain_real_database_thread(reader, monkeypatch, cancel_owned):
    path, _, _, _, _ = reader
    target = destination()
    entered, finish = threading.Event(), threading.Event()
    original = AuditDeliveryRepository.enroll
    def held(self, **kwargs):
        entered.set()
        assert finish.wait(5)
        return original(self, **kwargs)
    monkeypatch.setattr(AuditDeliveryRepository, 'enroll', held)
    async def never_send(*args, **kwargs):
        raise AssertionError('close during enrollment must not start transmission')
    monkeypatch.setattr('app.audit_exporter.send_audit_events', never_send)
    async def scenario():
        exporter = AuditExporter(path, target)
        waiting = asyncio.create_task(exporter.run_once())
        try:
            async with asyncio.timeout(2):
                while not entered.is_set(): await asyncio.sleep(.01)
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError): await waiting
            if cancel_owned:
                owned = next(iter(exporter._workers))
                owned.cancel()
                with pytest.raises(asyncio.CancelledError): await owned
            assert exporter.pending_count == 1
            with pytest.raises(AuditExporterError, match='not_admitted'): await exporter.run_once()
            with pytest.raises(RuntimeError, match='bounded_drain_timeout'): await exporter.close(.02)
            assert exporter.pending_count == 1
        finally:
            finish.set()
            await exporter.close(3)
        assert exporter.pending_count == 0
        assert repository(path, target).status()['pending'] == 1
    asyncio.run(scenario())


def test_cancelled_waiter_does_not_lose_success_ack(reader, monkeypatch):
    path, _, _, _, _ = reader
    target = destination()
    async def scenario():
        entered, finish = asyncio.Event(), asyncio.Event()
        async def held_sender(*args, **kwargs):
            entered.set()
            await finish.wait()
        monkeypatch.setattr('app.audit_exporter.send_audit_events', held_sender)
        exporter = AuditExporter(path, target)
        task = asyncio.create_task(exporter.run_once())
        try:
            await asyncio.wait_for(entered.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
            assert exporter.pending_count == 1
            finish.set()
        finally:
            await exporter.close(3)
        assert repository(path, target).status()['delivered'] == 1
    asyncio.run(scenario())


@pytest.mark.parametrize('delivery_schema,receiver_mode', [(5,'retry'),(7,'retry'),(7,'block')])
def test_real_receiver_lost_ack_then_automatic_ledger_retry(reader, certificate, monkeypatch, tmp_path, delivery_schema, receiver_mode):
    path, _, access, _, _ = reader
    for _ in range(2): access.create_console_session(user_id='user', lifetime_seconds=60)
    target = destination()
    cert, key = certificate
    if delivery_schema == 7:
        from app.migrations import migrate
        from app.audit_governance import AuditGovernanceRepository
        migrate(path, tmp_path/'before-governed.db', target_version=7)
        AuditGovernanceRepository(path).execute(command_id='register', operator_id='operator',
            destination_id=target.destination_id, scope_kind=target.scope_kind, scope_id=target.scope_id,
            action='register', expected_generation=0)
    sink = tmp_path/'sink.db'
    with sqlite3.connect(sink) as db: db.execute('CREATE TABLE received(id TEXT PRIMARY KEY)')
    async def scenario():
        calls = []
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        pending = set()
        async def receive(reader, writer):
            task = asyncio.current_task()
            pending.add(task)
            try:
                header = await reader.readuntil(b'\r\n\r\n')
                headers = dict(line.split(b': ', 1) for line in header.split(b'\r\n')[1:] if line)
                assert headers[b'Authorization'] == ('Bearer '+target.token).encode()
                body = await reader.readexactly(int(headers[b'Content-Length']))
                calls.append(body)
                if receiver_mode == 'block' and len(calls) == 1:
                    writer.write(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n')
                    await writer.drain()
                    return
                with sqlite3.connect(sink) as db:
                    db.executemany('INSERT OR IGNORE INTO received VALUES (?)',
                                   [(event['event_id'],) for event in json.loads(body)])
                if len(calls) > 1:
                    writer.write(b'HTTP/1.1 204 No Content\r\nX-Atom-Audit-Ack: '+
                                 hashlib.sha256(body).hexdigest().encode()+b'\r\n\r\n')
                    await writer.drain()
            finally:
                writer.close()
                pending.discard(task)
        server = await asyncio.start_server(receive, '127.0.0.1', 0, ssl=context)
        loop = asyncio.get_running_loop()
        original = loop.sock_connect
        async def routed(sock, address):
            assert address == ('8.8.8.8', 443)
            await original(sock, ('127.0.0.1', server.sockets[0].getsockname()[1]))
        monkeypatch.setattr(loop, 'sock_connect', routed)
        exporter = AuditExporter(path, target, ca_file=cert)
        try:
            first = await exporter.run_once()
            assert first.outcome == ('blocked' if receiver_mode == 'block' else 'retry') and first.event_count == 3
            assert repository(path, target).status()['delivered'] == 0
            if receiver_mode == 'block':
                await exporter.close()
                exporter = AuditExporter(path, target, ca_file=cert)
                assert (await exporter.run_once()).outcome == 'suspended'
                assert len(calls) == 1
                AuditGovernanceRepository(path).execute(command_id='resume', operator_id='operator',
                    destination_id=target.destination_id, scope_kind=target.scope_kind, scope_id=target.scope_id,
                    action='resume', expected_generation=2)
            monkeypatch.setattr('app.audit_delivery.time.time', lambda: 161 if receiver_mode == 'block' else 102)
            exporter.start(interval=.02)
            async with asyncio.timeout(3):
                while repository(path, target).status()['delivered'] != 3:
                    await asyncio.sleep(.01)
            assert repository(path, target).status()['delivered'] == 3
            assert calls[0] == calls[1]
            await asyncio.sleep(.06)
            assert len(calls) == 2
        finally:
            await exporter.close()
            server.close()
            await server.wait_closed()
            if pending: await asyncio.gather(*list(pending))
    asyncio.run(scenario())
    with sqlite3.connect(sink) as db: assert db.execute('SELECT count(*) FROM received').fetchone() == (3,)


def test_scheduler_stops_on_terminal_rejection_and_shutdown_wakes_sleep(reader, monkeypatch):
    path, _, _, _, _ = reader
    async def scenario():
        calls = []
        async def rejected(*args, **kwargs):
            calls.append(1)
            raise AuditSendError('fixture_denied', retryable=False)
        monkeypatch.setattr('app.audit_exporter.send_audit_events', rejected)
        exporter = AuditExporter(path, destination())
        try:
            exporter.start(.01)
            with pytest.raises(AuditExporterError, match='not_admitted'): exporter.start(.01)
            async with asyncio.timeout(2):
                while exporter.last_error != 'audit_export_configuration': await asyncio.sleep(.01)
            await asyncio.sleep(.05)
            assert calls == [1] and exporter.pending_count == 0
        finally:
            await exporter.close()
        second = AuditExporter(path, destination())
        second.start(300)
        await asyncio.sleep(.04)
        await asyncio.wait_for(second.close(), 1)
        assert second.pending_count == 0
    asyncio.run(scenario())
