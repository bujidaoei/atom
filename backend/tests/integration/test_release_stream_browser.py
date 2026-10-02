"""Real HTTPS EventSource behavior while the verified release workbench is open.

The browser connects directly to the isolated TLS Uvicorn server so the
long-lived response is never materialized by a Playwright route bridge.
"""

from datetime import datetime, timedelta, timezone
import ipaddress
import os
from pathlib import Path
import socket
import sqlite3
import sys
from threading import Thread
import time
from types import SimpleNamespace

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fastapi import FastAPI
from playwright.sync_api import sync_playwright
import pytest
import uvicorn

from app.artifacts import ArtifactStore
from app.config import get_settings
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
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, '127.0.0.1')])
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
            x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
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
    listener.bind(('127.0.0.1', 0))
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
    return server, thread, port


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
    payload, artifact = snapshot(b'<html>heat</html>')
    assert artifact == receipt.artifact
    root = tmp_path / 'artifacts'
    root.mkdir(mode=0o700)
    store = ArtifactStore(root)
    assert store.put(payload) == artifact

    app, token, engine = _configured_api(path, store, intent, tmp_path, monkeypatch)
    app.state.execution = SimpleNamespace(store=store, repository=RevisionRepository(path))
    app.state.verifier_client = object()
    app.include_router(auth.router, prefix='/api')
    app.include_router(projects.router, prefix='/api')
    app.include_router(verifications.router, prefix='/api')
    _static(app, DIST)
    outer = FastAPI()
    outer.mount('/atom', app)
    key, cert = _certificate(tmp_path)
    server, thread, port = _serve_https(outer, key, cert)
    origin = f'https://127.0.0.1:{port}'
    monkeypatch.setenv('ATOM_CONSOLE_ORIGIN', origin)
    get_settings.cache_clear()
    browser = context = None
    errors = []
    stream_responses = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='chromium')
            context = browser.new_context(viewport=viewport, ignore_https_errors=True,
                                          service_workers='block')
            context.add_cookies([{'name': '__Host-atom_console', 'value': token,
                'url': origin, 'secure': True, 'httpOnly': True, 'sameSite': 'Lax'}])
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('response', lambda response: stream_responses.append(response)
                if '/api/projects/project/events?' in response.url else None)
            page.goto(origin + '/atom/app/p/project', wait_until='domcontentloaded')
            page.get_by_role('tab', name='发布', exact=True).click()
            page.get_by_label('发布工作台').get_by_text('暂无已登记的发布指针').wait_for()
            page.get_by_role('button', name='连接中断，点击重连').wait_for(
                state='hidden', timeout=15000)
            deadline = time.monotonic() + 10
            while not stream_responses and time.monotonic() < deadline:
                page.wait_for_timeout(100)
            assert stream_responses and stream_responses[0].status == 200
            assert 'text/event-stream' in stream_responses[0].headers['content-type']

            context.set_offline(True)
            reconnect = page.get_by_role('button', name='连接中断，点击重连')
            reconnect.wait_for(timeout=15000)
            context.set_offline(False)
            reconnect.click()
            reconnect.wait_for(state='hidden', timeout=15000)
            page.get_by_role('tab', name='预览', exact=True).click()
            page.get_by_role('tab', name='发布', exact=True).click()
            page.reload(wait_until='domcontentloaded')
            page.get_by_role('tab', name='发布', exact=True).click()
            page.get_by_role('button', name='连接中断，点击重连').wait_for(
                state='hidden', timeout=15000)
            assert len([response for response in stream_responses
                        if response.status == 200]) >= 2
            assert not errors, errors
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    finally:
        if context is not None:
            context.close()
        if browser is not None:
            browser.close()
        server.should_exit = True
        thread.join(timeout=10)
        assert not thread.is_alive(), 'TLS API browser server did not stop'
        engine.dispose()
        get_settings.cache_clear()
