"""Authenticated v14 rollback control over the existing owner-scoped API."""
import asyncio
import os
import secrets
import socket
import sqlite3
import subprocess
import sys
from threading import Event
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.bounded_operations import BoundedOperations
from app.artifacts import ArtifactStore
from app.config import get_settings
from app.content_hosts import ContentHosts
from app.content_repository import ContentRepository
from app.db import get_db
from app.routers import releases
from app.security import issue_session
from test_adoption_repository import prepared
from test_adoption_verification_repository import adopted
from test_revision_migrations import legacy
from test_v13_content_consumers import published
from test_verifier_authority import authorized
from test_rollback_v14_repository import historical, _rollback_intent


def _configured_api(path, active_store, intent, tmp_path, monkeypatch):
    root = tmp_path / 'artifacts'
    values = {
        'ATOM_ENVIRONMENT':'production', 'ATOM_SANDBOX_MODE':'broker',
        'ATOM_SESSION_MODE':'durable', 'ATOM_CONSOLE_ORIGIN':'https://console.example.org',
        'ATOM_COOKIE_SECURE':'true', 'ATOM_SECRET':secrets.token_urlsafe(48),
        'ATOM_RUNTIME_TOKEN':secrets.token_urlsafe(48),
        'ATOM_RUNTIME_URL':'http://127.0.0.1:1',
        'ATOM_BROKER_ORIGIN':'http://127.0.0.1:2',
        'ATOM_BROKER_ADMIN_TOKEN':secrets.token_urlsafe(48),
        'ATOM_BROKER_GRANT_KEY':secrets.token_urlsafe(48),
        'ATOM_COMPLETION_GRANT_KEY':secrets.token_urlsafe(48),
        'ATOM_DATA_DIR':str(tmp_path / 'data'), 'ATOM_DB_PATH':str(path),
        'ATOM_ARTIFACT_DIR':str(root),
        'ATOM_CONTENT_HOST_SUFFIX':'apps.example.net',
        'ATOM_VERIFIER_ORIGIN':'http://127.0.0.1:3',
        'ATOM_VERIFIER_CONTROL_TOKEN':secrets.token_urlsafe(48),
        'ATOM_VERIFIER_POLICY_DIGEST':intent['policy_digest'],
        'ATOM_VERIFIER_RUNNER_VERSION':intent['runner_version'],
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    token = issue_session('user')
    engine = create_engine(f'sqlite:///{path}', connect_args={'check_same_thread':False})
    sessions = sessionmaker(bind=engine)
    app = FastAPI()
    app.include_router(releases.router, prefix='/api')
    app.state.release_operations = BoundedOperations(capacity=2)
    app.state.execution = SimpleNamespace(store=active_store)
    def database():
        with sessions() as session:
            yield session
    app.dependency_overrides[get_db] = database
    return app, token, engine


def _command(intent, source, displaced):
    args = _rollback_intent(intent, source, displaced)
    body = {'commandId': args['command_id'], 'newReleaseId':args['release_id'],
            'sourceReleaseId':args['source_release_id'],
            'expectedGeneration':args['expected_generation'],
            'expectedRevision':args['expected_revision']}
    route = f'/api/projects/project/releases/{displaced.release_id}/rollback'
    headers = {'origin':'https://console.example.org',
               'x-atom-intent':'rollback-verified-release'}
    return args, body, route, headers


def _assert_separate_content(path, root, binding_id, slug, expected_release):
    hosts = ContentHosts('apps.example.net')
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    environment = dict(os.environ, ATOM_CONTENT_DB_PATH=str(path),
        ATOM_CONTENT_ARTIFACT_DIR=str(root),
        ATOM_CONTENT_HOST_SUFFIX=hosts.suffix,
        ATOM_CONTENT_CONSOLE_ORIGIN='https://console.example.org')
    process = subprocess.Popen([sys.executable, '-m', 'uvicorn',
        'app.content_entry:create_app', '--factory', '--host', '127.0.0.1',
        '--port', str(port), '--no-access-log'], env=environment,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', trust_env=False,
                          timeout=1, follow_redirects=False) as client:
            deadline = time.monotonic() + 10
            while True:
                assert process.poll() is None, 'separate content process exited'
                try:
                    page = client.get('/', headers={'Host':hosts.hostname(binding_id)})
                    break
                except httpx.ConnectError:
                    assert time.monotonic() < deadline, 'separate content process did not start'
                    time.sleep(.05)
            assert page.status_code == 200 and page.content == b'<html>heat</html>'
            assert page.headers['x-atom-release'] == expected_release
            share = client.get('/s/' + slug, headers={'Host':'share.' + hosts.suffix})
            assert share.status_code == 307
            assert share.headers['location'] == hosts.url(binding_id)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@pytest.mark.parametrize('real_store', [False, True])
def test_owner_rollback_http_replays_and_denies_foreign_stale_malformed(
        historical, tmp_path, monkeypatch, real_store):
    path, store, intent, source, displaced = historical
    if real_store and sys.platform != 'linux':
        pytest.skip('ArtifactStore is Linux-only')
    root = tmp_path / 'artifacts'
    if real_store:
        root.mkdir(mode=0o700)
        active_store = ArtifactStore(root)
        assert active_store.put(store.payload).key == store.key
    else:
        active_store = store
    app, token, engine = _configured_api(path, active_store, intent, tmp_path, monkeypatch)
    args, body, route, headers = _command(intent, source, displaced)
    try:
        with TestClient(app, base_url='https://console.example.org',
                        cookies={'__Host-atom_console':token}) as client:
            assert client.post(route, json=body, headers={
                'origin':'https://console.example.org'}).status_code == 403
            assert client.post(route, json=body, headers=headers | {
                'origin':'https://foreign.example.org'}).status_code == 403
            assert client.post('/api/projects/foreign/releases/' + displaced.release_id +
                '/rollback', json=body, headers=headers).status_code == 404
            duplicate = b'{"commandId":"' + args['command_id'].encode() + b'","commandId":"' + args['command_id'].encode() + b'"}'
            assert client.post(route, content=duplicate, headers=headers | {
                'content-type':'application/json'}).status_code == 400
            assert client.post(route, json=body | {'policyDigest':'0' * 64},
                               headers=headers).status_code == 400
            assert client.post(route, json=body | {'expectedGeneration':3},
                               headers=headers).status_code == 409
            original_payload = store.payload
            if not real_store:
                store.payload = b'corrupt snapshot bytes'
                assert client.post(route, json=body, headers=headers).status_code == 409
                store.payload = original_payload
            result = client.post(route, json=body, headers=headers)
            assert result.status_code == 200, result.text
            assert result.json() == {'releaseId':args['release_id'],
                'sourceReleaseId':source.release_id,
                'displacedReleaseId':displaced.release_id,
                'generation':3, 'slug':intent['slug']}
            if real_store:
                binding = ContentRepository(path).sharing_binding(slug=intent['slug'])
                _assert_separate_content(path, root, binding.id, intent['slug'],
                                         args['release_id'])
            original_read = active_store.read
            monkeypatch.setattr(active_store, 'read',
                                lambda _key: pytest.fail('committed replay reread bytes'))
            assert client.post(route, json=body, headers=headers).json() == result.json()
            monkeypatch.setattr(active_store, 'read', original_read)
            assert client.post(route, json=body | {'newReleaseId':'d' * 32},
                               headers=headers).status_code == 409
        with TestClient(app, base_url='https://console.example.org') as anonymous:
            assert anonymous.post(route, json=body, headers=headers).status_code == 401
        with sqlite3.connect(path) as db:
            assert db.execute('SELECT source_release_id,displaced_release_id '
                'FROM release_rollback_sources').fetchone() == (
                source.release_id, displaced.release_id)
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_rollback_http_cancellation_keeps_owned_commit_and_replay(historical, tmp_path, monkeypatch):
    path, store, intent, source, displaced = historical
    entered, resume = Event(), Event()
    initial_reads = store.reads
    def pause_read():
        entered.set()
        assert resume.wait(10), 'release read was not resumed'
    store.hook = pause_read
    app, token, engine = _configured_api(path, store, intent, tmp_path, monkeypatch)
    args, body, route, headers = _command(intent, source, displaced)
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
            base_url='https://console.example.org', trust_env=False,
            cookies={'__Host-atom_console':token}) as client:
            pending = asyncio.create_task(client.post(route, json=body, headers=headers))
            assert await asyncio.to_thread(entered.wait, 5)
            try:
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending
                assert app.state.release_operations.pending_count == 1
                app.state.release_operations.close_admission()
                denied = await client.post(route, json=body, headers=headers)
                assert denied.status_code == 503
            finally:
                resume.set()
            await app.state.release_operations.drain(timeout=10)
            app.state.release_operations.start()
            store.hook = None
            replay = await client.post(route, json=body, headers=headers)
            assert replay.status_code == 200, replay.text
            assert replay.json()['releaseId'] == args['release_id']
            assert store.reads == initial_reads + 1
            assert app.state.release_operations.pending_count == 0
    try:
        asyncio.run(exercise())
        with sqlite3.connect(path) as db:
            assert db.execute('SELECT release_id,generation FROM release_publications').fetchone() == (
                args['release_id'], 3)
            assert db.execute('SELECT count(*) FROM release_rollback_sources').fetchone() == (1,)
    finally:
        resume.set()
        engine.dispose()
        get_settings.cache_clear()


def test_rollback_http_requires_exact_v14(published, tmp_path, monkeypatch):
    path, store, intent, release = published
    app, token, engine = _configured_api(path, store, intent, tmp_path, monkeypatch)
    body = {'commandId':'a' * 32, 'newReleaseId':'b' * 32,
            'sourceReleaseId':release.release_id, 'expectedGeneration':1,
            'expectedRevision':intent['expected_revision']}
    route = f'/api/projects/project/releases/{release.release_id}/rollback'
    try:
        with TestClient(app, base_url='https://console.example.org',
                        cookies={'__Host-atom_console':token}) as client:
            response = client.post(route, json=body, headers={
                'origin':'https://console.example.org',
                'x-atom-intent':'rollback-verified-release'})
            assert response.status_code == 503
        with sqlite3.connect(path) as db:
            assert db.execute('SELECT release_id,generation FROM release_publications').fetchone() == (
                release.release_id, 1)
            assert db.execute("SELECT count(*) FROM command_receipts WHERE key LIKE 'rollback:%'").fetchone() == (0,)
    finally:
        engine.dispose()
        get_settings.cache_clear()
