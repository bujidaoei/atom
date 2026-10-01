"""Real main lifecycle + password/session events + verified TLS receiver persistence."""
import asyncio
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sqlite3
import ssl
from threading import Event, Thread
import time

from fastapi.testclient import TestClient
import pytest

from app.audit_delivery import AuditDeliveryRepository
from app.audit_service import AuditExportService
from app.config import get_settings
from app.console_auth import DURABLE_COOKIE
from app.main import app
from app.migrations import migrate
from test_audit_destination import certificate
from test_audit_service import ENTRY
from test_durable_auth_routes import durable_client, LOGIN, ORIGIN


@pytest.mark.parametrize('mode', ['lost-ack', 'denied'])
def test_main_tls_export_recovery_and_revocation(durable_client, certificate, tmp_path, monkeypatch, capsys, mode):
    client, path = durable_client
    migrate(path, tmp_path/'before-v5.db', target_version=5)
    user = client.post('/api/auth/register', json=LOGIN).json()['id']
    assert client.post('/api/auth/login', json=LOGIN).status_code == 200
    cookie = client.cookies.get(DURABLE_COOKIE)
    cert, key = certificate
    sink = tmp_path/'receiver.db'
    with sqlite3.connect(sink) as db:
        db.execute('CREATE TABLE received(event_id TEXT PRIMARY KEY,payload TEXT NOT NULL)')
    config = get_settings()
    monkeypatch.setattr(config, 'audit_export_config', json.dumps([ENTRY|{'scope_id': user}]))
    monkeypatch.setattr(config, 'audit_export_interval_seconds', 1)
    monkeypatch.setattr(config, 'audit_export_ca_file', cert)
    monkeypatch.setattr(app.state, 'audit_exports', None, raising=False)
    target = config.audit_destinations[0]
    repo = AuditDeliveryRepository(path, destination_id=target.destination_id,
                                   scope_kind='account', scope_id=user)
    received = Event()
    calls, failures = [], []
    behavior = {'mode': mode}

    class Receiver(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *_args):
            pass

        def do_POST(self):
            self.connection.settimeout(3)
            try:
                assert self.path == target.path
                assert self.headers['Host'] == target.host
                assert self.headers['Authorization'] == 'Bearer '+target.token
                body = self.rfile.read(int(self.headers['Content-Length']))
                assert len(body) <= 262144
                assert self.headers['X-Atom-Audit-SHA256'] == hashlib.sha256(body).hexdigest()
                events = json.loads(body)
                assert all(event['scope_id'] == user and event['scope_kind'] == 'account' for event in events)
                assert cookie.encode() not in body and LOGIN['password'].encode() not in body
                calls.append(body)
                if behavior['mode'] == 'denied':
                    self.send_response(403)
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                else:
                    with sqlite3.connect(sink) as db:
                        db.executemany('INSERT OR IGNORE INTO received VALUES (?,?)',
                            [(event['event_id'], json.dumps(event, sort_keys=True)) for event in events])
                    if behavior['mode'] == 'lost-ack' and len(calls) == 1:
                        self.close_connection = True
                        return
                    self.send_response(204)
                    self.send_header('X-Atom-Audit-Ack', hashlib.sha256(body).hexdigest())
                    self.end_headers()
                self.close_connection = True
            except Exception:
                failures.append('receiver_fixture_failure')
            finally:
                received.set()

    server = ThreadingHTTPServer(('127.0.0.1', 0), Receiver)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original_start = AuditExportService.start
    async def routed_start(self):
        loop = asyncio.get_running_loop()
        original_connect = loop.sock_connect
        async def route(sock, address):
            if address == ('8.8.8.8', 443):
                return await original_connect(sock, ('127.0.0.1', server.server_port))
            raise AssertionError('unexpected_export_destination')
        monkeypatch.setattr(loop, 'sock_connect', route)
        await original_start(self)
    monkeypatch.setattr(AuditExportService, 'start', routed_start)

    def wait_for(predicate):
        deadline = time.monotonic()+8
        while not predicate():
            assert time.monotonic() < deadline, 'audit_state_deadline'
            time.sleep(.02)

    try:
        with TestClient(app, base_url=ORIGIN, headers={'Origin': ORIGIN}) as running:
            assert received.wait(5)
            if mode == 'lost-ack':
                wait_for(lambda: repo.status()['delivered'] == 2)
                assert calls[0] == calls[1]
            else:
                wait_for(lambda: app.state.audit_exports._exporters[0].last_error == 'audit_export_configuration')
                assert repo.status()['delivered'] == 0 and len(calls) == 1
            # Real logout must remain available even when the remote collector rejects export.
            response = running.post('/api/auth/logout-all', headers={
                'Cookie': DURABLE_COOKIE+'='+cookie, 'X-Atom-Intent': 'revoke-account-sessions'})
            assert response.status_code == 200
            assert running.get('/api/auth/me', headers={'Cookie': DURABLE_COOKIE+'='+cookie}).status_code == 401
            if mode == 'lost-ack': wait_for(lambda: repo.status()['delivered'] == 3)
        assert app.state.audit_exports.pending_count == 0
        assert app.state.execution is None
        if mode == 'denied':
            assert len(calls) == 1
            behavior['mode'] = 'ok'
            # Explicitly advance the lease clock for restart recovery; no fake transport/storage.
            wall_time = time.time
            monkeypatch.setattr('app.audit_delivery.time.time', lambda: wall_time()+61)
            with TestClient(app):
                wait_for(lambda: repo.status()['delivered'] == 3)
            assert app.state.audit_exports.pending_count == 0
        with sqlite3.connect(path) as db:
            db.row_factory = sqlite3.Row
            expected = {row['event_id']: dict(row) for row in db.execute('SELECT * FROM security_audit_events')}
            assert db.execute('SELECT count(*) FROM console_sessions WHERE revoked_at IS NULL').fetchone()[0] == 0
        with sqlite3.connect(sink) as db:
            stored = {row[0]: json.loads(row[1]) for row in db.execute('SELECT event_id,payload FROM received')}
        assert stored == expected and len(stored) == 3
        assert not failures
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)
        assert not thread.is_alive()
    captured = capsys.readouterr()
    assert target.token not in captured.out+captured.err
    assert cookie not in captured.out+captured.err
