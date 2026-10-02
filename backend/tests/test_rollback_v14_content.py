"""A rollback's fresh binding is delivered by the isolated content service."""
from contextlib import contextmanager
import os
import socket
import sqlite3
import subprocess
import sys
import time

import httpx
import pytest
from starlette.testclient import TestClient

from app.access_repository import AccessError
from app.artifacts import ArtifactStore
from app.content_access import ContentAccessRepository
from app.content_entry import ContentProcessConfig, create_app
from app.content_hosts import ContentHosts
from app.content_repository import ContentRepository
from app.content_service import ContentService
from app.release_repository import ReleaseRepository
from app.release_view import materialized_private_content
from app.verification_repository import VerificationError
from test_adoption_repository import prepared
from test_adoption_verification_repository import adopted
from test_revision_migrations import legacy
from test_v13_content_consumers import published
from test_verifier_authority import authorized
from test_rollback_v14_repository import historical, _rollback_intent


def test_v14_rollback_content_visibility_and_private_generation(historical):
    path, store, intent, source, displaced = historical
    releases = ReleaseRepository(path)
    content = ContentRepository(path)
    access = ContentAccessRepository(path)
    prior_binding = content.bind(owner='user', project_id='project',
                                 release_id=displaced.release_id)
    console = access.create_console_session(user_id='user', lifetime_seconds=900)
    old_bootstrap = access.bootstrap(binding_id=prior_binding.id)
    old_handoff = access.issue_handoff(viewer_id='user', source_session_id=console.id,
        binding_id=prior_binding.id, challenge=old_bootstrap.challenge)
    old_session = access.exchange(binding_id=prior_binding.id,
        handoff=old_handoff.secret, browser_nonce=old_bootstrap.secret)
    assert access.authorize(binding_id=prior_binding.id,
                            session_secret=old_session.secret).publication_generation == 2
    receipt = releases.rollback_verified(store, **_rollback_intent(intent, source, displaced))
    binding = content.sharing_binding(slug=intent['slug'])
    assert binding.release_id == receipt.release_id
    assert content.resolve(binding_id=binding.id).release_id == receipt.release_id
    with pytest.raises(AccessError, match='content_access_denied'):
        access.authorize(binding_id=prior_binding.id, session_secret=old_session.secret)
    fresh_bootstrap = access.bootstrap(binding_id=binding.id)
    fresh_handoff = access.issue_handoff(viewer_id='user', source_session_id=console.id,
        binding_id=binding.id, challenge=fresh_bootstrap.challenge)
    fresh_session = access.exchange(binding_id=binding.id,
        handoff=fresh_handoff.secret, browser_nonce=fresh_bootstrap.secret)
    assert access.authorize(binding_id=binding.id,
                            session_secret=fresh_session.secret).publication_generation == 3
    with materialized_private_content(content, access, store, binding_id=binding.id,
                                      session_secret=fresh_session.secret) as view:
        assert (view.path / 'index.html').read_bytes() == b'<html>heat</html>'
    service = ContentService(content, store, ContentHosts('content.example.test'))
    with TestClient(service, base_url='https://' + service.hosts.hostname(binding.id)) as client:
        page = client.get('/')
        assert page.status_code == 200 and page.content == b'<html>heat</html>'
        assert page.headers['x-atom-release'] == receipt.release_id
        share = client.get(service.hosts.sharing_url(intent['slug']), follow_redirects=False)
        assert share.status_code == 307 and share.headers['location'] == service.hosts.url(binding.id)
        releases.unpublish(owner='user', project_id='project', command_id='withdraw-restored',
            expected_release=receipt.release_id, expected_generation=3,
            require_verified_schema=True)
        assert client.get('/').status_code == 404
        assert client.get(service.hosts.sharing_url(intent['slug']),
                          follow_redirects=False).status_code == 404
    with pytest.raises(AccessError, match='content_access_denied'):
        access.authorize(binding_id=binding.id, session_secret=fresh_session.secret)
    with pytest.raises(AccessError, match='content_access_denied'):
        with materialized_private_content(content, access, store, binding_id=binding.id,
                                          session_secret=fresh_session.secret):
            pass
    with pytest.raises(VerificationError, match='release_not_found'):
        content.resolve(binding_id=binding.id)
    access.revoke_console_session(user_id='user', session_id=console.id)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM security_audit_events WHERE event_kind LIKE 'content.%'").fetchone() == (4,)
        assert db.execute("SELECT event_kind FROM security_audit_events WHERE event_kind LIKE 'console.%' ORDER BY sequence").fetchall() == [
            ('console.session.created',), ('console.session.revoked',)]
        dump = '\n'.join(db.iterdump())
        assert all(secret not in dump for secret in (
            old_bootstrap.secret, old_handoff.secret, old_session.secret,
            fresh_bootstrap.secret, fresh_handoff.secret, fresh_session.secret))


def test_v14_audit_failure_rolls_back_handoff(historical, monkeypatch):
    path, _store, _intent, _source, displaced = historical
    content = ContentRepository(path)
    binding = content.bind(owner='user', project_id='project', release_id=displaced.release_id)
    access = ContentAccessRepository(path)
    console = access.create_console_session(user_id='user', lifetime_seconds=900)
    bootstrap = access.bootstrap(binding_id=binding.id)
    original = access._transaction
    @contextmanager
    def deny_audit():
        with original() as db:
            db.set_authorizer(lambda action, table, *_: sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_INSERT and table == 'security_audit_events'
                else sqlite3.SQLITE_OK)
            yield db
    monkeypatch.setattr(access, '_transaction', deny_audit)
    with pytest.raises(AccessError, match='access_unavailable'):
        access.issue_handoff(viewer_id='user', source_session_id=console.id,
            binding_id=binding.id, challenge=bootstrap.challenge)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM content_handoffs').fetchone() == (0,)


@pytest.mark.skipif(sys.platform != 'linux', reason='ArtifactStore is Linux-only')
def test_v14_standalone_content_process_uses_real_retained_bytes(historical, tmp_path):
    path, fixture_store, intent, source, displaced = historical
    root = tmp_path / 'artifacts'
    root.mkdir(mode=0o700)
    store = ArtifactStore(root)
    assert store.put(fixture_store.payload).key == fixture_store.key
    receipt = ReleaseRepository(path).rollback_verified(store, **_rollback_intent(
        intent, source, displaced))
    binding = ContentRepository(path).sharing_binding(slug=intent['slug'])
    app = create_app(ContentProcessConfig(path, root, 'content.example.test',
                                          'https://console.example.org'))
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    environment = dict(os.environ, ATOM_CONTENT_DB_PATH=str(path),
        ATOM_CONTENT_ARTIFACT_DIR=str(root),
        ATOM_CONTENT_HOST_SUFFIX='content.example.test',
        ATOM_CONTENT_CONSOLE_ORIGIN='https://console.example.org')
    worker = subprocess.Popen([sys.executable, '-m', 'uvicorn',
        'app.content_entry:create_app', '--factory', '--host', '127.0.0.1',
        '--port', str(port), '--no-access-log'], env=environment,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f'http://127.0.0.1:{port}'
    try:
        with httpx.Client(timeout=1, follow_redirects=False) as client:
            deadline = time.monotonic() + 10
            while True:
                if worker.poll() is not None:
                    pytest.fail('content process exited before startup')
                try:
                    page = client.get(url + '/', headers={'Host':app.hosts.hostname(binding.id)})
                    break
                except httpx.ConnectError:
                    if time.monotonic() >= deadline:
                        pytest.fail('content process did not start')
                    time.sleep(0.05)
            assert page.status_code == 200 and page.headers['x-atom-release'] == receipt.release_id
            assert page.content == b'<html>heat</html>'
            share = client.get(url + '/s/' + intent['slug'],
                               headers={'Host':'share.content.example.test'})
            assert share.status_code == 307 and share.headers['location'] == app.hosts.url(binding.id)
            ReleaseRepository(path).unpublish(owner='user', project_id='project',
                command_id='withdraw-restored', expected_release=receipt.release_id,
                expected_generation=3, require_verified_schema=True)
            assert client.get(url + '/', headers={'Host':app.hosts.hostname(binding.id)}).status_code == 404
            assert client.get(url + '/s/' + intent['slug'],
                              headers={'Host':'share.content.example.test'}).status_code == 404
    finally:
        worker.terminate()
        try:
            worker.wait(timeout=5)
        except subprocess.TimeoutExpired:
            worker.kill()
            worker.wait(timeout=5)
