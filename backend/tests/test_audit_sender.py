import asyncio
import hashlib
import json
import sqlite3
import ssl

import pytest

from app.audit_delivery import AuditDeliveryRepository
from app.audit_sender import AuditSendError, encode_batch, send_audit_events
from test_audit_destination import certificate, destination
from test_audit_repository import reader, audited_release, release, ledger, legacy


@pytest.fixture
def batch(reader):
    path, repository, access, source, _ = reader
    for _ in range(2):
        access.create_console_session(user_id='user', lifetime_seconds=60)
    return path, repository.page(user_id='user', source_session_id=source.id).events


@pytest.mark.parametrize('change', ['empty', 'unknown', 'scope', 'duplicate', 'control', 'nested', 'nan'])
def test_payload_validation_precedes_network(batch, change):
    _, events = batch
    events = [dict(events[0])]
    if change == 'empty': events = []
    elif change == 'unknown': events[0]['secret'] = 'sentinel-never-export'
    elif change == 'scope': events[0]['scope_id'] = 'other'
    elif change == 'duplicate': events += events
    elif change == 'control': events[0]['operation_id'] = 'line\nbreak'
    elif change == 'nested': events[0]['operation_id'] = {'raw': 'secret'}
    elif change == 'nan': events[0]['sequence'] = float('nan')
    with pytest.raises(AuditSendError, match='invalid_audit_batch') as error:
        asyncio.run(send_audit_events(destination(), events))
    assert error.value.retryable is False


@pytest.mark.parametrize('case', ['ok', 'lost-ack', 'wrong-ack', 'missing-ack', 'duplicate-ack',
    'redirect', 'denied', 'busy', 'server-error', 'wrong-success', 'oversized', 'malformed',
    'body-framing', 'informational-flood', 'silent', 'drip', 'cancel'])
def test_actual_tls_batch_and_ack_failure_matrix(batch, certificate, monkeypatch, tmp_path, case, capsys):
    path, events = batch
    target = destination()
    repository = AuditDeliveryRepository(path, destination_id=target.destination_id,
                                        scope_kind=target.scope_kind, scope_id=target.scope_id)
    repository.enroll()
    lease = repository.claim()
    cert, key = certificate
    receiver_db = tmp_path/'receiver.db'
    with sqlite3.connect(receiver_db) as db:
        db.execute('CREATE TABLE received(event_id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    calls = []
    async def scenario():
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        pending, writers = set(), []
        received = asyncio.Event()
        async def handle(reader, writer):
            task = asyncio.current_task()
            pending.add(task)
            writers.append(writer)
            try:
                headers = await reader.readuntil(b'\r\n\r\n')
                lines = headers.split(b'\r\n')
                assert lines[0] == b'POST /events HTTP/1.1'
                pairs = dict(line.split(b': ', 1) for line in lines[1:] if line)
                assert pairs[b'Host'] == target.host.encode()
                assert pairs[b'Authorization'] == ('Bearer '+target.token).encode()
                body = await reader.readexactly(int(pairs[b'Content-Length']))
                assert body == encode_batch(target, events)
                assert target.token.encode() not in body
                assert pairs[b'X-Atom-Audit-SHA256'] == hashlib.sha256(body).hexdigest().encode()
                calls.append(body)
                with sqlite3.connect(receiver_db) as db:
                    for event in json.loads(body):
                        db.execute('INSERT OR IGNORE INTO received VALUES (?,?)',
                                   (event['event_id'], json.dumps(event)))
                received.set()
                current = 'ok' if case == 'lost-ack' and len(calls) > 1 else case
                ack = hashlib.sha256(body).hexdigest().encode()
                reply = b'HTTP/1.1 204 No Content\r\nX-Atom-Audit-Ack: '+ack+b'\r\n\r\n'
                if current == 'lost-ack': return
                if current == 'wrong-ack': reply = reply.replace(ack, b'0'*64)
                if current == 'missing-ack': reply = b'HTTP/1.1 204 No Content\r\n\r\n'
                if current == 'duplicate-ack': reply = reply[:-2]+b'X-Atom-Audit-Ack: '+ack+b'\r\n\r\n'
                if current == 'redirect': reply = b'HTTP/1.1 307 Temporary Redirect\r\nLocation: https://127.0.0.1/secret\r\nContent-Length: 0\r\n\r\n'
                if current in ('denied', 'busy', 'server-error', 'wrong-success'):
                    code = {'denied': b'403', 'busy': b'429', 'server-error': b'503', 'wrong-success': b'200'}[current]
                    reply = b'HTTP/1.1 '+code+b' Reflect-'+target.token.encode()+b'\r\nContent-Length: 0\r\n\r\n'
                if current == 'oversized': reply = b'HTTP/1.1 204 No Content\r\nX-Fill: '+b'a'*17000+b'\r\n\r\n'
                if current == 'malformed': reply = b'bad '+target.token.encode()+b'\r\n\r\n'
                if current == 'body-framing': reply = reply[:-2]+b'Transfer-Encoding: chunked\r\n\r\n'
                if current == 'informational-flood': reply = b'HTTP/1.1 100 Continue\r\n\r\n'*5+reply
                if current in ('silent', 'cancel'):
                    assert await reader.read() == b''
                    return
                if current == 'drip':
                    for byte in reply:
                        writer.write(bytes([byte]))
                        await writer.drain()
                        await asyncio.sleep(.02)
                else:
                    writer.write(reply)
                    await writer.drain()
            except (OSError, asyncio.CancelledError):
                pass
            finally:
                writer.close()
                pending.discard(task)
        server = await asyncio.start_server(handle, '127.0.0.1', 0, ssl=context)
        port = server.sockets[0].getsockname()[1]
        loop = asyncio.get_running_loop()
        original = loop.sock_connect
        async def route(sock, address):
            assert address == ('8.8.8.8', 443)
            await original(sock, ('127.0.0.1', port))
        monkeypatch.setattr(loop, 'sock_connect', route)
        try:
            task = asyncio.create_task(send_audit_events(target, lease.events, ca_file=cert,
                                                       timeout=.3 if case in ('silent', 'drip') else 3))
            if case == 'cancel':
                await asyncio.wait_for(received.wait(), 2)
                task.cancel()
                with pytest.raises(asyncio.CancelledError): await task
            elif case == 'ok':
                await task
                repository.acknowledge(event_ids=[event['event_id'] for event in lease.events], lease_owner=lease.owner)
            else:
                with pytest.raises(AuditSendError) as error: await task
                assert target.token not in str(error.value)
                if case in ('redirect', 'denied', 'wrong-success'):
                    assert error.value.retryable is False
                else:
                    assert error.value.retryable is True
            if case == 'lost-ack':
                assert repository.status()['delivered'] == 0
                repository.retry(event_ids=[event['event_id'] for event in lease.events], lease_owner=lease.owner)
                monkeypatch.setattr('app.audit_delivery.time.time', lambda: 102)
                retried = repository.claim()
                await send_audit_events(target, retried.events, ca_file=cert)
                repository.acknowledge(event_ids=[event['event_id'] for event in retried.events], lease_owner=retried.owner)
                assert calls[0] == calls[1]
            assert repository.status()['delivered'] == (len(events) if case in ('ok', 'lost-ack') else 0)
            assert len(calls) == (2 if case == 'lost-ack' else 1)
        finally:
            server.close()
            await server.wait_closed()
            for writer in writers: writer.close()
            for task in list(pending): task.cancel()
            if pending: await asyncio.gather(*list(pending), return_exceptions=True)
    asyncio.run(scenario())
    with sqlite3.connect(receiver_db) as db:
        assert db.execute('SELECT count(*) FROM received').fetchone() == (len(events),)
    captured = capsys.readouterr()
    assert target.token not in captured.out+captured.err
