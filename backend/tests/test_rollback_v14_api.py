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
from app.migrations import migrate
from app.release_repository import ReleaseRepository
from app.routers import releases, verifications
from app.security import issue_session
from app.verification_repository import VerificationError, VerificationRepository
from app.verifier_authority import VerifierAuthority
from test_adoption_repository import Store, prepared, snapshot
from test_adoption_verification_repository import adopted
from test_revision_migrations import legacy
from test_v13_content_consumers import published
from test_verifier_authority import authorized, _intent, _register
from test_rollback_v14_repository import historical, _rollback_intent


@pytest.fixture
def http_history(adopted, tmp_path):
    path, adopted_receipt, intent = adopted
    migrate(path, tmp_path / 'before-v13.db', target_version=13)
    request = VerificationRepository(path).reserve(**(intent | {'request_id':'a' * 32}))
    authority = VerifierAuthority(path)
    assignment = authority.dispatch(owner='user', request_id=request.id,
        artifact=adopted_receipt.artifact, route_id='b' * 32,
        verifier_id='http-worker', environment_digest='e' * 64)
    _register(authority, assignment,
        [{'key':'page', 'checkIndex':0, 'passed':True, 'note':'observed'}])
    payload, artifact = snapshot(b'<html>heat</html>')
    assert artifact == adopted_receipt.artifact
    store = Store(artifact.key, payload)
    release_intent = _intent(request) | {'release_id':'c' * 32}
    source = ReleaseRepository(path).publish_verified(store, **release_intent)
    displaced = ReleaseRepository(path).publish_verified(store, **(release_intent | {
        'release_id':'d' * 32, 'expected_generation':1}))
    return path, store, release_intent, source, displaced


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


def test_v14_current_and_withdraw_follow_rollback(historical, tmp_path, monkeypatch):
    path, store, intent, source, displaced = historical
    app, token, engine = _configured_api(path, store, intent, tmp_path, monkeypatch)
    args, body, route, headers = _command(intent, source, displaced)
    current_route = '/api/projects/project/releases/current'
    inspect_headers = {'x-atom-intent':'inspect-verified-release'}
    try:
        with TestClient(app, base_url='https://console.example.org',
                        cookies={'__Host-atom_console':token}) as client:
            before = client.get(current_route, headers=inspect_headers)
            assert before.status_code == 200, before.text
            assert before.json()['publication']['releaseId'] == displaced.release_id
            assert before.json()['publication']['generation'] == 2
            assert client.post(route, json=body, headers=headers).status_code == 200
            current = client.get(current_route, headers=inspect_headers)
            assert current.status_code == 200, current.text
            publication = current.json()['publication']
            assert publication['releaseId'] == args['release_id']
            assert publication['generation'] == 3 and publication['live'] is True
            assert publication['pinnedUrl'].startswith('https://r-')
            withdraw_route = '/api/projects/project/releases/' + args['release_id'] + '/unpublish'
            withdraw_body = {'commandId':'f' * 32, 'expectedGeneration':3}
            withdraw_headers = {'origin':'https://console.example.org',
                                'x-atom-intent':'unpublish-verified-release'}
            withdrawn = client.post(withdraw_route, json=withdraw_body,
                                    headers=withdraw_headers)
            assert withdrawn.status_code == 200, withdrawn.text
            assert withdrawn.json()['generation'] == 4
            assert client.post(withdraw_route, json=withdraw_body,
                               headers=withdraw_headers).json() == withdrawn.json()
            after = client.get(current_route, headers=inspect_headers)
            assert after.status_code == 200
            assert after.json()['publication']['live'] is False
            assert after.json()['publication']['pinnedUrl'] is None
            assert after.json()['publication']['sharingUrl'] is None
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_verified_v13_current_withdraw_and_publish_regression(http_history, tmp_path, monkeypatch):
    path, store, intent, _source, displaced = http_history
    app, token, engine = _configured_api(path, store, intent, tmp_path, monkeypatch)
    route = '/api/projects/project/releases'
    try:
        with TestClient(app, base_url='https://console.example.org',
                        cookies={'__Host-atom_console':token}) as client:
            current = client.get(route + '/current',
                headers={'x-atom-intent':'inspect-verified-release'})
            assert current.status_code == 200
            assert current.json()['publication']['releaseId'] == displaced.release_id
            withdrawal = client.post(route + '/' + displaced.release_id + '/unpublish',
                json={'commandId':'e' * 32, 'expectedGeneration':2},
                headers={'origin':'https://console.example.org',
                         'x-atom-intent':'unpublish-verified-release'})
            assert withdrawal.status_code == 200 and withdrawal.json()['generation'] == 3
            publish = client.post(route, json={
                'releaseId':'f' * 32, 'verificationId':intent['verification_id'],
                'expectedRevision':intent['expected_revision'],
                'expectedGeneration':3, 'audience':'public', 'slug':intent['slug']},
                headers={'origin':'https://console.example.org',
                         'x-atom-intent':'publish-verified-release'})
            assert publish.status_code == 200, publish.text
            assert publish.json()['generation'] == 4
            assert client.get(route + '/current',
                headers={'x-atom-intent':'inspect-verified-release'}).json()['publication']['releaseId'] == 'f' * 32
    finally:
        engine.dispose()
        get_settings.cache_clear()


@pytest.mark.parametrize('real_store', [False, True])
@pytest.mark.parametrize('schema_version', [14, 15])
def test_verified_rollback_withdraw_and_subsequent_publish_http(
        http_history, tmp_path, monkeypatch, real_store, schema_version):
    path, fixture_store, intent, source, displaced = http_history
    if real_store and sys.platform != 'linux':
        pytest.skip('ArtifactStore is Linux-only')
    migrate(path, tmp_path / 'before-v14.db', target_version=14)
    if schema_version == 15:
        migrate(path, tmp_path / 'before-v15.db', target_version=15)
    root = tmp_path / 'artifacts'
    if real_store:
        root.mkdir(mode=0o700)
        store = ArtifactStore(root)
        assert store.put(fixture_store.payload).key == fixture_store.key
    else:
        store = fixture_store
    app, token, engine = _configured_api(path, store, intent, tmp_path, monkeypatch)
    args, body, rollback_route, rollback_headers = _command(intent, source, displaced)
    route = '/api/projects/project/releases'
    try:
        with TestClient(app, base_url='https://console.example.org',
                        cookies={'__Host-atom_console':token}) as client:
            rolled = client.post(rollback_route, json=body, headers=rollback_headers)
            assert rolled.status_code == 200, rolled.text
            current = client.get(route + '/current',
                headers={'x-atom-intent':'inspect-verified-release'})
            assert current.status_code == 200
            assert current.json()['publication']['releaseId'] == args['release_id']
            withdrawn = client.post(route + '/' + args['release_id'] + '/unpublish',
                json={'commandId':'e' * 32, 'expectedGeneration':3},
                headers={'origin':'https://console.example.org',
                         'x-atom-intent':'unpublish-verified-release'})
            assert withdrawn.status_code == 200, withdrawn.text
            assert withdrawn.json()['generation'] == 4
            assert client.get(route + '/current',
                headers={'x-atom-intent':'inspect-verified-release'}).json()['publication']['live'] is False
            published_again = client.post(route, json={
                'releaseId':'f' * 32, 'verificationId':intent['verification_id'],
                'expectedRevision':intent['expected_revision'],
                'expectedGeneration':4, 'audience':'public', 'slug':intent['slug']},
                headers={'origin':'https://console.example.org',
                         'x-atom-intent':'publish-verified-release'})
            assert published_again.status_code == 200, published_again.text
            assert published_again.json()['generation'] == 5
            final = client.get(route + '/current',
                headers={'x-atom-intent':'inspect-verified-release'}).json()['publication']
            assert final['releaseId'] == 'f' * 32 and final['generation'] == 5
            assert final['live'] is True and final['pinnedUrl'].startswith('https://r-')
            if real_store:
                binding = ContentRepository(path).sharing_binding(slug=intent['slug'])
                _assert_separate_content(path, root, binding.id, intent['slug'], 'f' * 32)
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_verified_http_routes_reject_untrusted_v10_ledger(legacy, tmp_path, monkeypatch):
    path, _baseline = legacy
    migrate(path, tmp_path / 'before-v10.db', target_version=10)
    intent = {'policy_digest':'c' * 64, 'runner_version':'runner-1'}
    app, token, engine = _configured_api(path, Store('0' * 64, b''),
                                         intent, tmp_path, monkeypatch)
    app.include_router(verifications.router, prefix='/api')
    app.state.verifier_client = object()
    route = '/api/projects/project/releases'
    try:
        with TestClient(app, base_url='https://console.example.org',
                        cookies={'__Host-atom_console':token}) as client:
            current = client.get(route + '/current',
                headers={'x-atom-intent':'inspect-verified-release'})
            assert current.status_code == 503
            assert client.get('/api/projects/project/verifications/latest').status_code == 503
            publish = client.post(route, json={
                'releaseId':'a' * 32, 'verificationId':'b' * 32,
                'expectedRevision':'root', 'expectedGeneration':0,
                'audience':'public', 'slug':'untrusted-site'},
                headers={'origin':'https://console.example.org',
                         'x-atom-intent':'publish-verified-release'})
            assert publish.status_code == 503
        with sqlite3.connect(path) as db:
            assert db.execute('SELECT count(*) FROM release_publications').fetchone() == (0,)
    finally:
        engine.dispose()
        get_settings.cache_clear()


@pytest.mark.parametrize('version', [13, 14, 15])
def test_latest_verification_is_owner_scoped_and_survives_nonready_project(
        http_history, tmp_path, monkeypatch, version):
    path, store, intent, _source, _displaced = http_history
    if version >= 14:
        migrate(path, tmp_path / 'before-v14-latest.db', target_version=14)
    if version == 15:
        migrate(path, tmp_path / 'before-v15-latest.db', target_version=15)
    repository = VerificationRepository(path)
    expected = repository.describe(owner='user', project_id='project', request_id='a' * 32)
    assert repository.latest(owner='user', project_id='project') == expected
    with pytest.raises(VerificationError, match='verification_not_found'):
        repository.latest(owner='foreign', project_id='project')
    with sqlite3.connect(path) as db:
        db.execute("UPDATE projects SET status='cancelled' WHERE id='project'")
        db.execute("UPDATE revision_workspaces SET current_revision_id='root' "
                   "WHERE project_id='project' AND heat_id IS NULL")
    assert repository.latest(owner='user', project_id='project') == expected

    app, token, engine = _configured_api(path, store, intent, tmp_path, monkeypatch)
    app.include_router(verifications.router, prefix='/api')
    app.state.verifier_client = object()
    try:
        with TestClient(app, base_url='https://console.example.org',
                        cookies={'__Host-atom_console':token}) as client:
            route = '/api/projects/project/verifications/latest'
            latest = client.get(route)
            assert latest.status_code == 200, latest.text
            assert latest.json()['verification'] == {
                'requestId':'a' * 32, 'revisionId':expected.request.revision_id,
                'contractDigest':expected.request.contract.digest, 'state':'passed',
                'deadline':expected.request.deadline, 'total':1, 'passed':1,
                'completedAt':expected.result.completed_at}
            assert client.get(route + '?other=1').status_code == 400
            assert client.get(route, headers={'origin':'https://foreign.example.org'}).status_code == 400
            assert client.get('/api/projects/other/verifications/latest').status_code == 404
        with TestClient(app, base_url='https://console.example.org') as anonymous:
            assert anonymous.get(route).status_code == 401
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_latest_verification_empty_verified_history(adopted, tmp_path):
    path, _receipt, _intent = adopted
    migrate(path, tmp_path / 'before-v13-empty.db', target_version=13)
    assert VerificationRepository(path).latest(owner='user', project_id='project') is None
