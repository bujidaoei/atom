"""Configured v13 exporter against real console events and a TLS receiver."""
import asyncio
import hashlib
import json
import sqlite3
import ssl

from app.audit_governance import AuditGovernanceRepository
from app.audit_service import AuditExportService
from app.audit_delivery import AuditDeliveryRepository
from app.migrations import verify
from test_audit_service import ENTRY, settings
from test_audit_destination import certificate
from test_revision_migrations import legacy
from test_v13_audit_delivery import delivery


def test_v13_service_retries_lost_tls_ack_and_drains(delivery, certificate, tmp_path, monkeypatch):
    path, _ = delivery
    assert verify(path) == 13
    cert, key = certificate
    config = settings(db_path=path, audit_export_config=json.dumps([ENTRY]),
        audit_export_ca_file=cert, audit_export_interval_seconds=1)
    target = config.audit_destinations[0]
    AuditGovernanceRepository(path).execute(command_id='register-tls', operator_id='operator',
        destination_id=target.destination_id, scope_kind=target.scope_kind, scope_id=target.scope_id,
        action='register', expected_generation=0)
    repository = AuditDeliveryRepository(path, destination_id=target.destination_id,
        scope_kind='account', scope_id='user')
    clock = [100]
    monkeypatch.setattr('app.audit_delivery.time.time', lambda: clock[0])
    sink = tmp_path / 'received.db'
    with sqlite3.connect(sink) as db:
        db.execute('CREATE TABLE received(event_id TEXT PRIMARY KEY, payload TEXT NOT NULL)')

    async def scenario():
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        pending = set()
        calls = []

        async def receive(reader, writer):
            task = asyncio.current_task()
            pending.add(task)
            try:
                header = await reader.readuntil(b'\r\n\r\n')
                lines = header.split(b'\r\n')
                assert lines[0] == b'POST /events HTTP/1.1'
                fields = dict(line.split(b': ', 1) for line in lines[1:] if line)
                assert fields[b'Host'] == target.host.encode()
                assert fields[b'Authorization'] == ('Bearer ' + target.token).encode()
                body = await reader.readexactly(int(fields[b'Content-Length']))
                calls.append(body)
                with sqlite3.connect(sink) as db:
                    for event in json.loads(body):
                        db.execute('INSERT OR IGNORE INTO received VALUES (?,?)',
                            (event['event_id'], json.dumps(event, sort_keys=True)))
                if len(calls) > 1:
                    writer.write(b'HTTP/1.1 204 No Content\r\nX-Atom-Audit-Ack: ' +
                        hashlib.sha256(body).hexdigest().encode() + b'\r\n\r\n')
                    await writer.drain()
            finally:
                writer.close()
                pending.discard(task)

        server = await asyncio.start_server(receive, '127.0.0.1', 0, ssl=context)
        loop = asyncio.get_running_loop()
        original_connect = loop.sock_connect

        async def route(sock, address):
            assert address == ('8.8.8.8', 443)
            await original_connect(sock, ('127.0.0.1', server.sockets[0].getsockname()[1]))

        monkeypatch.setattr(loop, 'sock_connect', route)
        service = AuditExportService(config)
        try:
            await service.start()
            async with asyncio.timeout(3):
                while len(calls) < 1 or repository.status()['pending'] != 5:
                    await asyncio.sleep(.02)
            assert repository.status()['delivered'] == 0
            clock[0] = 103  # The first attempt's two-second durable retry backoff has elapsed.
            async with asyncio.timeout(6):
                while repository.status()['delivered'] != 5 or service._exporters[0].last_error is not None:
                    await asyncio.sleep(.02)
            assert len(calls) == 2 and calls[0] == calls[1]
            assert service._exporters[0].last_error is None
            assert repository.status()['backlog'] == 0
        finally:
            await service.close()
            server.close()
            await server.wait_closed()
            if pending:
                await asyncio.gather(*list(pending))
        assert service.pending_count == 0

    asyncio.run(scenario())
    with sqlite3.connect(sink) as db:
        assert db.execute('SELECT count(*) FROM received').fetchone() == (5,)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM security_audit_delivery WHERE destination_id=? AND state=?',
            (target.destination_id, 'delivered')).fetchone() == (5,)
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
