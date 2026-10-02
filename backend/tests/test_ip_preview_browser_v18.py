"""Real Chromium and TLS on one IP with separate immutable project ports."""
from datetime import datetime, timedelta, timezone
from ipaddress import ip_address
import socket
import ssl
from threading import Thread
import time

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from playwright.sync_api import sync_playwright
import pytest
import uvicorn
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.access_repository import AccessRepository
from app.content_repository import ContentRepository
from app.content_service import ContentService
from app.migrations import migrate
from app.models import Project
from app.preview_access import PreviewAccessRepository
from app.preview_service import PreviewService
from app.ip_ingress import IngressError, IpIngressConfig, probe_ip_routes
from app.project_origins import OriginRoute, ProjectOriginRepository
from app.project_port_hosts import ProjectPortHosts
from app.project_public_hosts import ProjectPublicHosts
from app.release_repository import ReleaseRepository
from app.revisions import RevisionRepository
from test_adoption_repository import prepared, snapshot
from test_adoption_verification_repository import adopted
from test_revision_migrations import legacy
from test_rollback_v14_repository import historical
from test_v13_content_consumers import published
from test_verifier_authority import authorized


def _tls_files(tmp_path):
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, '127.0.0.1')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ip_address('127.0.0.1'))]),
                           critical=False).sign(key, hashes.SHA256()))
    key_file, cert_file = tmp_path / 'key.pem', tmp_path / 'cert.pem'
    key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return key_file, cert_file


def _adjacent_listeners(count=2):
    for port in range(21000, 21500, count):
        sockets = []
        try:
            for candidate in range(port, port + count):
                listener = socket.socket()
                listener.bind(('127.0.0.1', candidate))
                listener.listen(32)
                sockets.append(listener)
            return sockets
        except OSError:
            for listener in sockets:
                listener.close()
    raise AssertionError('no adjacent local TLS ports available')


def _start(app, listener, key, cert):
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=listener.getsockname()[1],
        ssl_keyfile=str(key), ssl_certfile=str(cert), log_level='error', access_log=False,
        proxy_headers=False))
    thread = Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert thread.is_alive() and time.monotonic() < deadline
        time.sleep(.02)
    return server, thread


def test_browser_preview_exchange_storage_and_public_port_separation(historical, tmp_path):
    path, _original_store, _intent, _source, _displaced = historical
    for version in range(15, 19):
        migrate(path, tmp_path / f'before-v{version}.db', target_version=version)
    html = (b'<html><body><span id="state"></span><script>'
            b'const key="draft-state";'
            b'document.querySelector("#state").textContent=localStorage.getItem(key)||"new";'
            b'</script></body></html>')
    payload, artifact = snapshot(html)
    engine = create_engine('sqlite:///' + path.as_posix())
    with Session(engine) as db:
        db.add(Project(id='browser-project', user_id='user', prompt='Browser origin test',
                       title='Browser origin test', status='ready'))
        db.commit()
    engine.dispose()
    revisions = RevisionRepository(path)
    workspace = revisions.ensure_workspace('user', 'browser-project')
    revision = revisions.bootstrap('user', workspace, artifact)
    class Store:
        def read(self, key):
            assert key == artifact.key
            return payload
    store = Store()
    ReleaseRepository(path, required_schema=16).publish_snapshot(store,
        verification_mode='advisory', owner='user', project_id='browser-project',
        release_id='1' * 32, verification_id=None, expected_revision=revision,
        expected_generation=0, policy_digest=None, runner_version=None,
        audience='public', slug='browser-origin-test')
    listeners = _adjacent_listeners()
    preview_port = listeners[0].getsockname()[1]
    public_port = listeners[1].getsockname()[1]
    origins = ProjectOriginRepository(path, first_port=preview_port, last_port=public_port)
    assert origins.reserve('browser-project').preview_port == preview_port
    source = AccessRepository(path).create_console_session(user_id='user', lifetime_seconds=900)
    access = PreviewAccessRepository(path)
    grant = access.issue(owner_id='user', source_session_id=source.id,
                         project_id='browser-project', revision_id=revision)
    hosts = ProjectPortHosts('127.0.0.1', origins)
    preview = PreviewService(access, store, hosts)
    public = ContentService(ContentRepository(path), store,
        ProjectPublicHosts('127.0.0.1', origins, ContentRepository(path)))
    key, cert = _tls_files(tmp_path)
    services = []
    try:
        services.append(_start(preview, listeners[0], key, cert))
        services.append(_start(public, listeners[1], key, cert))
        probe_config = IpIngressConfig('127.0.0.1', 'preview:8000', 'public:8000',
            'https://acme.example.test/directory')
        probe_ip_routes(origins.active_routes(), probe_config.address,
                        tls_context=ssl.create_default_context(cafile=str(cert)))
        with pytest.raises(IngressError, match='ingress_probe_mismatch'):
            probe_ip_routes((OriginRoute('wrong-project', 'preview', preview_port),),
                            probe_config.address, tls_context=ssl.create_default_context(cafile=str(cert)))
        with pytest.raises(IngressError, match='ingress_probe_unavailable'):
            probe_ip_routes(origins.active_routes(), probe_config.address, timeout_seconds=2)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(ignore_https_errors=True, service_workers='block')
            try:
                page = context.new_page()
                page.goto(hosts.origin(preview_port) + '/_atom/open#' + grant.secret)
                page.wait_for_url(hosts.origin(preview_port) + '/', timeout=10000)
                assert page.locator('#state').inner_text() == 'new'
                page.evaluate("localStorage.setItem('draft-state','kept')")
                page.reload()
                assert page.locator('#state').inner_text() == 'kept'
                assert grant.secret not in page.url
                assert '__Host-atom_preview_' not in page.evaluate('document.cookie')
                assert any(item['name'] == f'__Host-atom_preview_{preview_port}'
                           for item in context.cookies([hosts.origin(public_port)]))
                visitor = context.new_page()
                visitor.goto(hosts.origin(public_port) + '/')
                assert visitor.locator('#state').inner_text() == 'new'
                assert visitor.evaluate("localStorage.getItem('draft-state')") is None
                visitor.evaluate("localStorage.setItem('public-state','kept')")
                visitor.reload()
                assert visitor.evaluate("localStorage.getItem('public-state')") == 'kept'
                assert page.evaluate("localStorage.getItem('public-state')") is None
                assert visitor.evaluate("fetch(location.origin.replace(/:\\d+$/, ':" + str(preview_port) + "') + '/', {credentials:'include'}).then(() => 'readable').catch(() => 'blocked')") == 'blocked'
                AccessRepository(path).revoke_console_session(user_id='user', session_id=source.id)
                page.reload()
                assert page.locator('body').inner_text() == ''
            finally:
                context.close()
                browser.close()
    finally:
        for server, thread in services:
            server.should_exit = True
            thread.join(timeout=15)
            assert not thread.is_alive()
        for listener in listeners:
            listener.close()


def test_two_projects_have_independent_browser_storage_and_preview_authority(historical, tmp_path):
    path, _original_store, _intent, _source, _displaced = historical
    for version in range(15, 19):
        migrate(path, tmp_path / f'before-two-v{version}.db', target_version=version)
    html = (b'<html><body><span id="project"></span><script>'
            b'document.querySelector("#project").textContent='
            b'localStorage.getItem("project-marker")||"empty";'
            b'</script></body></html>')
    payload, artifact = snapshot(html)
    class Store:
        def read(self, key):
            assert key == artifact.key
            return payload
    store = Store()
    engine = create_engine('sqlite:///' + path.as_posix())
    with Session(engine) as db:
        for project_id in ('isolation-a', 'isolation-b'):
            db.add(Project(id=project_id, user_id='user', prompt=project_id,
                           title=project_id, status='ready'))
        db.commit()
    engine.dispose()
    revisions = RevisionRepository(path)
    revision_ids = {}
    for project_id in ('isolation-a', 'isolation-b'):
        workspace = revisions.ensure_workspace('user', project_id)
        revision = revisions.bootstrap('user', workspace, artifact)
        revision_ids[project_id] = revision
        ReleaseRepository(path, required_schema=16).publish_snapshot(
            store,
            verification_mode='advisory', owner='user', project_id=project_id,
            release_id=('a' if project_id.endswith('a') else 'b') * 32,
            verification_id=None, expected_revision=revision, expected_generation=0,
            policy_digest=None, runner_version=None, audience='public',
            slug=project_id)
    listeners = _adjacent_listeners(4)
    ports = [listener.getsockname()[1] for listener in listeners]
    origins = ProjectOriginRepository(path, first_port=ports[0], last_port=ports[-1])
    a, b = origins.reserve('isolation-a'), origins.reserve('isolation-b')
    assert (a.preview_port, a.public_port, b.preview_port, b.public_port) == tuple(ports)
    source = AccessRepository(path).create_console_session(user_id='user', lifetime_seconds=900)
    access = PreviewAccessRepository(path)
    grant = access.issue(owner_id='user', source_session_id=source.id,
                         project_id='isolation-a', revision_id=revision_ids['isolation-a'])
    preview = PreviewService(access, store, ProjectPortHosts('127.0.0.1', origins))
    public = ContentService(ContentRepository(path), store,
        ProjectPublicHosts('127.0.0.1', origins, ContentRepository(path)))
    key, cert = _tls_files(tmp_path)
    services = []
    try:
        for listener in listeners:
            purpose = origins.route(listener.getsockname()[1]).purpose
            services.append(_start(preview if purpose == 'preview' else public,
                                   listener, key, cert))
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(ignore_https_errors=True, service_workers='block')
            try:
                owner = context.new_page()
                owner.goto(f'https://127.0.0.1:{a.preview_port}/_atom/open#{grant.secret}')
                owner.wait_for_url(f'https://127.0.0.1:{a.preview_port}/', timeout=10000)
                assert owner.locator('#project').inner_text() == 'empty'
                owner.evaluate("localStorage.setItem('project-marker','owner-a')")
                public_a, public_b = context.new_page(), context.new_page()
                public_a.goto(f'https://127.0.0.1:{a.public_port}/')
                public_b.goto(f'https://127.0.0.1:{b.public_port}/')
                assert public_a.locator('#project').inner_text() == 'empty'
                assert public_b.locator('#project').inner_text() == 'empty'
                public_a.evaluate("localStorage.setItem('project-marker','public-a')")
                public_b.evaluate("localStorage.setItem('project-marker','public-b')")
                for page, expected in ((owner, 'owner-a'), (public_a, 'public-a'),
                                       (public_b, 'public-b')):
                    page.reload()
                    assert page.locator('#project').inner_text() == expected
                foreign_preview = context.new_page()
                foreign_preview.goto(f'https://127.0.0.1:{b.preview_port}/')
                assert foreign_preview.locator('body').inner_text() == ''
                # The browser sends IP-scoped cookies to every port. A forged
                # cookie from project B must not grant access to project B's preview.
                public_b.evaluate("document.cookie='__Host-atom_preview_" +
                    str(b.preview_port) + "=forged; Secure; Path=/'")
                foreign_preview.reload()
                assert foreign_preview.locator('body').inner_text() == ''
                assert owner.locator('#project').inner_text() == 'owner-a'
            finally:
                context.close()
                browser.close()
    finally:
        for server, thread in services:
            server.should_exit = True
            thread.join(timeout=15)
            assert not thread.is_alive()
        for listener in listeners:
            listener.close()
