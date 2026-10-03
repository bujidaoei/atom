"""Real HTTPS EventSource behavior while the verified release workbench is open.

The browser connects directly to the isolated TLS Uvicorn server so the
long-lived response is never materialized by a Playwright route bridge.
"""

from contextlib import contextmanager, ExitStack
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import socket
import sys
from threading import Thread
import time
from types import SimpleNamespace

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fastapi import FastAPI, Request
from fastapi.responses import Response
from playwright.sync_api import sync_playwright
import pytest
from sqlalchemy.orm import Session
import uvicorn

from app import events as events_module
from app.artifacts import ArtifactStore
from app.config import get_settings
from app.console_auth import proof_for_new_session
from app.migrations import migrate
from app.revisions import RevisionRepository
from app.routers import auth, projects, verifications
from test_adoption_repository import prepared, snapshot
from test_adoption_verification_repository import adopted
from test_release_workbench_browser import _static
from test_revision_migrations import legacy
from test_rollback_v14_api import _configured_api


DIST = Path('/usr/share/nginx/html')
pytestmark = pytest.mark.skipif(
    sys.platform != 'linux' or not os.environ.get('ATOM_BROWSER_STREAM_TEST'),
    reason='requires target Linux pinned browser and built SPA')


def _certificate(directory: Path) -> tuple[Path, Path]:
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'console.example.org')])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([
            x509.DNSName('console.example.org')]), critical=False)
        .sign(key, hashes.SHA256())
    )
    key_path = directory / 'tls-key.pem'
    cert_path = directory / 'tls-cert.pem'
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.chmod(0o600)
    cert_path.chmod(0o600)
    return key_path, cert_path


def _serve_https(app: FastAPI, key: Path, cert: Path):
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(('127.0.0.1', 443))
    listener.listen(128)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port,
        ssl_keyfile=str(key), ssl_certfile=str(cert), log_level='error',
        access_log=False, proxy_headers=False))
    thread = Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert thread.is_alive() and time.monotonic() < deadline, 'TLS API did not start'
        time.sleep(.02)
    return server, thread, listener, port


@pytest.mark.parametrize('viewport', [
    pytest.param({'width': 1280, 'height': 800}, id='desktop'),
    pytest.param({'width': 390, 'height': 844}, id='mobile'),
])
def test_release_workbench_keeps_real_event_stream_and_recovers(
        adopted, tmp_path, monkeypatch, viewport):
    assert DIST.joinpath('index.html').is_file()
    path, receipt, intent = adopted
    migrate(path, tmp_path / 'before-stream-v13.db', target_version=13)
    migrate(path, tmp_path / 'before-stream-v14.db', target_version=14)
    migrate(path, tmp_path / 'before-stream-v15.db', target_version=15)
    migrate(path, tmp_path / 'before-stream-v16.db', target_version=16)
    payload, artifact = snapshot(b'<html>heat</html>')
    assert artifact == receipt.artifact
    root = tmp_path / 'artifacts'
    root.mkdir(mode=0o700)
    store = ArtifactStore(root)
    assert store.put(payload) == artifact

    monkeypatch.setenv('ATOM_CONSOLE_PROOF_REQUIRED', 'true')
    app, token, engine = _configured_api(path, store, intent, tmp_path, monkeypatch)
    proof = proof_for_new_session(token)
    @contextmanager
    def event_session():
        with Session(engine) as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
    monkeypatch.setattr(events_module, 'session_scope', event_session)
    app.state.execution = SimpleNamespace(store=store, repository=RevisionRepository(path))
    app.state.verifier_client = object()
    app.include_router(auth.router, prefix='/api')
    app.include_router(projects.router, prefix='/api')
    app.include_router(verifications.router, prefix='/api')
    _static(app, DIST)
    stream_gate = SimpleNamespace(available=True)
    @app.middleware('http')
    async def stream_fault_gate(request: Request, call_next):
        if request.url.path.endswith('/events') and not stream_gate.available:
            return Response(status_code=503)
        return await call_next(request)

    @app.post('/__test/close-stream')
    async def close_stream():
        stream_gate.available = False
        await events_module.bus.publish('project', 'stream.resync', {})
        return {'ok': True}

    @app.post('/__test/emit-stream')
    async def emit_stream():
        await events_module.bus.publish('project', 'message.completed',
                                        {'text': 'stream-live-marker'},
                                        run_id='stream-check', role='alex')
        return {'ok': True}

    outer = FastAPI()
    outer.mount('/atom', app)
    key, cert = _certificate(tmp_path)
    server, thread, listener, port = _serve_https(outer, key, cert)
    assert port == 443
    origin = 'https://console.example.org'
    monkeypatch.setenv('ATOM_CONSOLE_ORIGIN', origin)
    get_settings.cache_clear()
    errors = []
    stream_responses = []
    try:
        with sync_playwright() as playwright, ExitStack() as cleanup:
            browser = playwright.chromium.launch(channel='chromium')
            cleanup.callback(browser.close)
            context = browser.new_context(viewport=viewport, ignore_https_errors=True,
                                          service_workers='block')
            cleanup.callback(context.close)
            context.add_cookies([{'name': '__Host-atom_console', 'value': token,
                'url': origin, 'secure': True, 'httpOnly': True, 'sameSite': 'Lax'}])
            without_proof = context.request.get(
                origin + '/atom/api/projects/project/events?after=0')
            assert without_proof.status == 401
            context.add_init_script(
                script="localStorage.setItem('atom.console.proof.v1', "
                       + repr(proof) + ")")
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('response', lambda response: stream_responses.append(response)
                if '/api/projects/project/events?' in response.url else None)
            page.goto(origin + '/atom/app/p/project', wait_until='domcontentloaded')
            page.get_by_role('tab', name='发布', exact=True).click()
            page.get_by_label('发布与历史', exact=True).get_by_text('准备好分享你的作品了吗？').wait_for()
            page.get_by_role('button', name='连接中断，点击重连').wait_for(
                state='hidden', timeout=15000)
            deadline = time.monotonic() + 10
            while not stream_responses and time.monotonic() < deadline:
                page.wait_for_timeout(100)
            assert stream_responses and stream_responses[0].status == 200
            assert 'text/event-stream' in stream_responses[0].headers['content-type']
            emitted = page.request.post(origin + '/atom/__test/emit-stream')
            assert emitted.status == 200 and emitted.json() == {'ok': True}
            page.get_by_text('stream-live-marker').wait_for(timeout=10000)

            fault = page.request.post(origin + '/atom/__test/close-stream')
            assert fault.status == 200 and fault.json() == {'ok': True}
            reconnect = page.get_by_role('button', name='连接中断，点击重连')
            reconnect.wait_for(timeout=15000)
            stream_gate.available = True
            reconnect.click()
            reconnect.wait_for(state='hidden', timeout=15000)
            deadline = time.monotonic() + 10
            while len([r for r in stream_responses if r.status == 200]) < 2 and time.monotonic() < deadline:
                page.wait_for_timeout(100)
            assert len([r for r in stream_responses if r.status == 200]) >= 2
            page.get_by_role('tab', name='预览', exact=True).click()
            page.get_by_role('tab', name='发布', exact=True).click()
            before_reload = len([r for r in stream_responses if r.status == 200])
            page.reload(wait_until='domcontentloaded')
            page.get_by_role('tab', name='发布', exact=True).click()
            page.get_by_role('button', name='连接中断，点击重连').wait_for(
                state='hidden', timeout=15000)
            deadline = time.monotonic() + 10
            while len([r for r in stream_responses if r.status == 200]) <= before_reload and time.monotonic() < deadline:
                page.wait_for_timeout(100)
            assert len([r for r in stream_responses if r.status == 200]) > before_reload
            assert not errors, errors
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
        assert not thread.is_alive(), 'TLS API browser server did not stop'
        engine.dispose()
        get_settings.cache_clear()
