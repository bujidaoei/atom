"""Authenticated v13 console route through private Uvicorn and real Chromium."""
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
import time
from types import SimpleNamespace
from threading import Event

from fastapi import FastAPI
import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.artifacts import ArtifactStore
from app.bounded_operations import BoundedOperations
from app.config import get_settings
from app.content_hosts import ContentHosts
from app.db import get_db
from app.migrations import migrate
from app.release_repository import ReleaseRepository
from app.routers import releases, verifications
from app.security import issue_session
from app.verifier_client import VerifierClient
from test_adoption_repository import prepared, snapshot
from test_adoption_verification_repository import adopted
from test_revision_migrations import legacy


IMAGE = os.environ.get('ATOM_VERIFIER_TEST_IMAGE_DIGEST')
PROFILE = Path(__file__).resolve().parents[3] / 'deploy' / 'verifier-seccomp.json'
pytestmark = pytest.mark.skipif(sys.platform != 'linux' or not IMAGE or
    not os.environ.get('ATOM_VERIFIER_TEST_REAL_STORE'),
    reason='requires target Linux daemon, real ArtifactStore and pinned Chromium')


def _port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


@asynccontextmanager
async def separate_content_process(path, root):
    port = _port()
    environment = dict(os.environ, ATOM_CONTENT_DB_PATH=str(path),
        ATOM_CONTENT_ARTIFACT_DIR=str(root), ATOM_CONTENT_HOST_SUFFIX='apps.example.net',
        ATOM_CONTENT_CONSOLE_ORIGIN='https://console.example.org')
    process = await asyncio.create_subprocess_exec(sys.executable, '-m', 'uvicorn',
        'app.content_entry:create_app', '--factory', '--host', '127.0.0.1',
        '--port', str(port), '--log-level', 'error', env=environment,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 15
        async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{port}',
                                     trust_env=False, timeout=2) as probe:
            while True:
                assert process.returncode is None, 'separate content process failed startup'
                try:
                    response = await probe.get('/', headers={'host':'share.apps.example.net'})
                    assert response.status_code == 404
                    break
                except httpx.ConnectError:
                    assert time.monotonic() < deadline
                    await asyncio.sleep(.05)
        yield port
    finally:
        if process.returncode is None:
            process.terminate()
        try:
            await asyncio.wait_for(process.communicate(), 10)
        except TimeoutError:
            process.kill()
            await asyncio.wait_for(process.communicate(), 5)
        assert process.returncode is not None


def test_authenticated_main_routes_reconcile_real_browser_result(adopted, tmp_path, monkeypatch):
    path, receipt, _intent = adopted
    checks = [{'type':'exists','selector':'body'}]
    with sqlite3.connect(path) as db:
        db.execute('UPDATE requirements SET checks_json=? WHERE project_id=?',
                   (json.dumps(checks), 'project'))
    migrate(path, tmp_path / 'before-v13.db', target_version=13)
    payload, artifact = snapshot(b'<html>heat</html>')
    assert artifact == receipt.artifact
    root = tmp_path / 'artifacts'
    root.mkdir(mode=0o700)
    assert ArtifactStore(root).put(payload) == artifact
    token = secrets.token_urlsafe(48)
    port = _port()
    environment = dict(os.environ, ATOM_VERIFIER_DB_PATH=str(path),
        ATOM_VERIFIER_ARTIFACT_DIR=str(root), ATOM_VERIFIER_IMAGE=IMAGE,
        ATOM_VERIFIER_SECCOMP_PATH=str(PROFILE), ATOM_VERIFIER_ID='api-route-worker',
        ATOM_VERIFIER_CONTROL_TOKEN=token)
    process = subprocess.Popen([sys.executable, '-m', 'uvicorn',
        'app.verifier_service:create_app', '--factory', '--host','127.0.0.1',
        '--port',str(port), '--log-level','error'], env=environment,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', trust_env=False,
                          timeout=2) as probe:
            deadline = time.monotonic() + 15
            while True:
                assert process.poll() is None, 'private verifier failed startup'
                try:
                    assert probe.get('/health').json() == {'ok':True}
                    break
                except httpx.ConnectError:
                    assert time.monotonic() < deadline
                    time.sleep(.05)
        values = {
            'ATOM_ENVIRONMENT':'production', 'ATOM_SANDBOX_MODE':'broker',
            'ATOM_SESSION_MODE':'durable', 'ATOM_CONSOLE_ORIGIN':'https://console.example.org',
            'ATOM_COOKIE_SECURE':'true', 'ATOM_SECRET':'synthetic-main-key-32-characters-long',
            'ATOM_RUNTIME_TOKEN':'synthetic-runtime-key-32-characters-long',
            'ATOM_RUNTIME_URL':'http://127.0.0.1:1',
            'ATOM_BROKER_ORIGIN':'http://127.0.0.1:2',
            'ATOM_BROKER_ADMIN_TOKEN':'synthetic-broker-admin-key-32-characters',
            'ATOM_BROKER_GRANT_KEY':'synthetic-broker-grant-key-32-characters',
            'ATOM_COMPLETION_GRANT_KEY':'synthetic-completion-key-32-characters',
            'ATOM_DATA_DIR':str(tmp_path / 'data'), 'ATOM_DB_PATH':str(path),
            'ATOM_ARTIFACT_DIR':str(root),
            'ATOM_CONTENT_HOST_SUFFIX':'apps.example.net',
            'ATOM_PUBLICATION_VERIFICATION':'required',
            'ATOM_VERIFIER_ORIGIN':f'http://127.0.0.1:{port}',
            'ATOM_VERIFIER_CONTROL_TOKEN':token,
            'ATOM_VERIFIER_POLICY_DIGEST':'c' * 64,
            'ATOM_VERIFIER_RUNNER_VERSION':'runner-1',
        }
        for name, value in values.items():
            monkeypatch.setenv(name, value)
        get_settings.cache_clear()
        session_token = issue_session('user')
        engine = create_engine(f'sqlite:///{path}', connect_args={'check_same_thread':False})
        sessions = sessionmaker(bind=engine)
        api = FastAPI()
        api.include_router(verifications.router, prefix='/api')
        api.include_router(releases.router, prefix='/api')
        api.state.release_operations = BoundedOperations(capacity=2)
        api.state.execution = SimpleNamespace(store=ArtifactStore(root))
        def database():
            with sessions() as session:
                yield session
        api.dependency_overrides[get_db] = database

        async def exercise():
            async with VerifierClient(f'http://127.0.0.1:{port}', token) as trusted:
                await trusted.require_ready()
                api.state.verifier_client = trusted
                route = '/api/projects/project/verifications'
                intent_headers = {'origin':'https://console.example.org'}
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api),
                    base_url='https://console.example.org', trust_env=False,
                    cookies={'__Host-atom_console':session_token}) as client:
                    key = secrets.token_hex(16)
                    denied = await client.post(route, json={'requestId':key},
                                               headers={'origin':'https://foreign.example.org'})
                    assert denied.status_code == 403
                    duplicate = await client.post(route,
                        content=b'{"requestId":"' + key.encode() + b'","requestId":"'
                                + key.encode() + b'"}',
                        headers=intent_headers | {'content-type':'application/json'})
                    assert duplicate.status_code == 400
                    reserved = await client.post(route, json={'requestId':key},
                                                 headers=intent_headers)
                    assert reserved.status_code == 200, reserved.text
                    data = reserved.json()
                    assert data['requestId'] == key
                    assert data['revisionId'] == receipt.revision_id
                    assert data['state'] == 'reserved'
                    replay = await client.post(route, json={'requestId':key},
                                               headers=intent_headers)
                    assert replay.status_code == 200 and replay.json() == data
                    before = await client.get(route + '/' + key)
                    assert before.status_code == 200 and before.json()['state'] == 'reserved'
                    latest_reserved = await client.get(route + '/latest')
                    assert latest_reserved.status_code == 200
                    assert latest_reserved.json()['verification'] == {
                        **before.json(), 'current': True}
                    result = await client.post(route + '/' + key + '/run',
                                               headers=intent_headers)
                    assert result.status_code == 200, result.text
                    assert result.json()['state'] == 'passed'
                    assert result.json()['total'] == result.json()['passed'] == 1
                    settled = await client.get(route + '/' + key)
                    assert settled.status_code == 200 and settled.json() == result.json()
                    latest_passed = await client.get(route + '/latest')
                    assert latest_passed.status_code == 200
                    assert latest_passed.json()['verification'] == {
                        **settled.json(), 'current': True}
                    repeat = await client.post(route + '/' + key + '/run',
                                               headers=intent_headers)
                    assert repeat.status_code == 200 and repeat.json() == result.json()
                    release_route = '/api/projects/project/releases'
                    release_command = {'releaseId':secrets.token_hex(16),
                        'verificationId':key, 'expectedRevision':receipt.revision_id,
                        'expectedGeneration':0, 'audience':'public', 'slug':'verified-page'}
                    release_headers = intent_headers | {'x-atom-intent':'publish-verified-release'}
                    denied_release = await client.post(release_route, json=release_command,
                        headers={'origin':'https://foreign.example.org',
                                 'x-atom-intent':'publish-verified-release'})
                    assert denied_release.status_code == 403
                    foreign_release = await client.post('/api/projects/other/releases',
                        json=release_command, headers=release_headers)
                    assert foreign_release.status_code == 404
                    with sqlite3.connect(path) as db:
                        db.execute("UPDATE revision_workspaces SET current_revision_id='root' "
                                   "WHERE project_id='project' AND heat_id IS NULL")
                    stale_head = await client.post(release_route, json=release_command,
                                                   headers=release_headers)
                    assert stale_head.status_code == 409
                    with sqlite3.connect(path) as db:
                        db.execute('UPDATE revision_workspaces SET current_revision_id=? '
                                   'WHERE project_id=? AND heat_id IS NULL',
                                   (receipt.revision_id, 'project'))
                        requirement = db.execute('SELECT id,title FROM requirements '
                                                 'WHERE project_id=? ORDER BY position,id LIMIT 1',
                                                 ('project',)).fetchone()
                        assert requirement is not None
                        db.execute('UPDATE requirements SET title=? WHERE id=?',
                                   (requirement[1] + ' changed', requirement[0]))
                    stale_contract = await client.post(release_route, json=release_command,
                                                       headers=release_headers)
                    assert stale_contract.status_code == 409
                    with sqlite3.connect(path) as db:
                        db.execute('UPDATE requirements SET title=? WHERE id=?',
                                   (requirement[1], requirement[0]))
                    stored = root / (artifact.key + '.atomsnap')
                    stored.unlink()
                    try:
                        missing = await client.post(release_route, json=release_command,
                                                    headers=release_headers)
                        assert missing.status_code == 503
                    finally:
                        assert api.state.execution.store.put(payload) == artifact
                    stored.write_bytes(b'broken-snapshot')
                    try:
                        corrupt = await client.post(release_route, json=release_command,
                                                    headers=release_headers)
                        assert corrupt.status_code == 503
                    finally:
                        stored.write_bytes(payload)
                    assert await asyncio.to_thread(ReleaseRepository(path).current,
                        owner='user', project_id='project') is None
                    store = api.state.execution.store
                    original_read = store.read
                    started, resume = Event(), Event()
                    def delayed_read(key):
                        started.set()
                        assert resume.wait(10)
                        return original_read(key)
                    monkeypatch.setattr(store, 'read', delayed_read)
                    lost = asyncio.create_task(client.post(release_route,
                        json=release_command, headers=release_headers))
                    assert await asyncio.to_thread(started.wait, 5)
                    lost.cancel()
                    assert isinstance((await asyncio.gather(lost, return_exceptions=True))[0],
                                      asyncio.CancelledError)
                    assert api.state.release_operations.pending_count == 1
                    api.state.release_operations.close_admission()
                    closed = await client.get(release_route+'/current',
                        headers={'x-atom-intent':'inspect-verified-release'})
                    assert closed.status_code == 503
                    draining = asyncio.create_task(api.state.release_operations.drain())
                    await asyncio.sleep(.05)
                    assert not draining.done()
                    resume.set()
                    await asyncio.wait_for(draining, 10)
                    api.state.release_operations.start()
                    deadline = time.monotonic() + 10
                    while True:
                        pointer_after_loss = await asyncio.to_thread(
                            ReleaseRepository(path).current, owner='user', project_id='project')
                        if pointer_after_loss is not None and api.state.release_operations.pending_count == 0:
                            break
                        assert time.monotonic() < deadline
                        await asyncio.sleep(.02)
                    assert pointer_after_loss.release_id == release_command['releaseId']
                    def forbidden_read(_key):
                        raise AssertionError('committed replay read artifact again')
                    monkeypatch.setattr(store, 'read', forbidden_read)
                    replay_release = await client.post(release_route, json=release_command,
                                                       headers=release_headers)
                    assert replay_release.status_code == 200, replay_release.text
                    assert replay_release.json() == {'releaseId':release_command['releaseId'],
                        'revisionId':receipt.revision_id, 'generation':1, 'slug':'verified-page'}
                    monkeypatch.setattr(store, 'read', original_read)
                    current = await client.get(release_route+'/current',
                        headers={'x-atom-intent':'inspect-verified-release'})
                    assert current.status_code == 200, current.text
                    pointer = current.json()['publication']
                    assert pointer['releaseId'] == release_command['releaseId']
                    assert pointer['revisionId'] == receipt.revision_id
                    assert pointer['live'] is True and pointer['audience'] == 'public'
                    assert pointer['pinnedUrl'].startswith('https://r-')
                    assert pointer['pinnedUrl'].endswith('.apps.example.net/')
                    assert pointer['sharingUrl'] == 'https://share.apps.example.net/s/verified-page'
                    stale = await client.post(release_route,
                        json=release_command | {'releaseId':secrets.token_hex(16),
                                                'expectedGeneration':0},
                        headers=release_headers)
                    assert stale.status_code == 409
                    duplicate = await client.post(release_route,
                        content=b'{"releaseId":"' + release_command['releaseId'].encode() +
                                b'","releaseId":"' + release_command['releaseId'].encode() + b'"}',
                        headers=release_headers | {'content-type':'application/json'})
                    assert duplicate.status_code == 400
                    foreign = await client.get('/api/projects/other/verifications/' + key)
                    assert foreign.status_code == 404
                    hosts = ContentHosts('apps.example.net')
                    pinned_host = {'host':hosts.hostname(pointer['bindingId'])}
                    sharing_host = {'host':'share.' + hosts.suffix}
                    async with separate_content_process(path, root) as content_port, \
                        httpx.AsyncClient(base_url=f'http://127.0.0.1:{content_port}',
                                          trust_env=False, timeout=5) as published:
                        page = await published.get('/', headers=pinned_host)
                        assert page.status_code == 200 and page.content == b'<html>heat</html>'
                        shared = await published.get('/s/verified-page', headers=sharing_host)
                        assert shared.status_code == 307
                        assert shared.headers['location'] == pointer['pinnedUrl']
                        revoke_route = release_route + '/' + release_command['releaseId'] + '/unpublish'
                        revoke_headers = intent_headers | {'x-atom-intent':'unpublish-verified-release'}
                        revoke_command = {'commandId':secrets.token_hex(16),
                                          'expectedGeneration':1}
                        wrong_origin = await client.post(revoke_route, json=revoke_command,
                            headers={'origin':'https://foreign.example.org',
                                     'x-atom-intent':'unpublish-verified-release'})
                        assert wrong_origin.status_code == 403
                        wrong_owner = await client.post(
                            '/api/projects/other/releases/' + release_command['releaseId'] + '/unpublish',
                            json=revoke_command, headers=revoke_headers)
                        assert wrong_owner.status_code == 404
                        stale_revoke = await client.post(revoke_route,
                            json=revoke_command | {'expectedGeneration':2},
                            headers=revoke_headers)
                        assert stale_revoke.status_code == 409
                        revoked = await client.post(revoke_route, json=revoke_command,
                                                    headers=revoke_headers)
                        assert revoked.status_code == 200, revoked.text
                        assert revoked.json() == {'commandId':revoke_command['commandId'],
                            'releaseId':release_command['releaseId'], 'generation':2}
                        replay_revoke = await client.post(revoke_route, json=revoke_command,
                                                          headers=revoke_headers)
                        assert replay_revoke.status_code == 200
                        assert replay_revoke.json() == revoked.json()
                        after = await client.get(release_route+'/current',
                            headers={'x-atom-intent':'inspect-verified-release'})
                        assert after.status_code == 200
                        assert after.json()['publication']['live'] is False
                        assert after.json()['publication']['generation'] == 2
                        assert after.json()['publication']['pinnedUrl'] is None
                        assert after.json()['publication']['sharingUrl'] is None
                        assert (await published.get('/', headers=pinned_host)).status_code == 404
                        assert (await published.get('/s/verified-page',
                                                    headers=sharing_host)).status_code == 404
                    competing = [release_command | {'releaseId':secrets.token_hex(16),
                        'expectedGeneration':2} for _ in range(2)]
                    outcomes = await asyncio.gather(*(client.post(release_route,
                        json=command, headers=release_headers) for command in competing))
                    assert sorted(response.status_code for response in outcomes) == [200, 409]
                    winner = next(response.json() for response in outcomes
                                  if response.status_code == 200)
                    assert winner['releaseId'] in {item['releaseId'] for item in competing}
                    assert winner['generation'] == 3
                    latest = await client.get(release_route+'/current',
                                              headers={'x-atom-intent':'inspect-verified-release'})
                    assert latest.status_code == 200
                    assert latest.json()['publication']['releaseId'] == winner['releaseId']
                    assert latest.json()['publication']['generation'] == 3
                    slow_checks = [{'type':'flow','selector':'#missing','expect':'body'}]
                    with sqlite3.connect(path) as db:
                        db.execute('UPDATE requirements SET checks_json=? WHERE project_id=?',
                                   (json.dumps(slow_checks), 'project'))
                    slow_key = secrets.token_hex(16)
                    next_request = await client.post(route, json={'requestId':slow_key},
                                                     headers=intent_headers)
                    assert next_request.status_code == 200
                    async with VerifierClient(f'http://127.0.0.1:{port}', token,
                                              timeout=1) as short:
                        api.state.verifier_client = short
                        uncertain = await client.post(route + '/' + slow_key + '/run',
                                                      headers=intent_headers)
                        assert uncertain.status_code == 202
                        assert uncertain.json()['state'] == 'running'
                    api.state.verifier_client = trusted
                    deadline = time.monotonic() + 30
                    while True:
                        later = await client.get(route + '/' + slow_key)
                        if later.json()['state'] == 'failed':
                            assert later.json()['total'] == 1
                            assert later.json()['passed'] == 0
                            break
                        assert later.json()['state'] in ('running','unresolved')
                        assert time.monotonic() < deadline
                        await asyncio.sleep(.1)
                    no_redispatch = await client.post(route + '/' + slow_key + '/run',
                                                      headers=intent_headers)
                    assert no_redispatch.status_code == 200
                    assert no_redispatch.json() == later.json()
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api),
                    base_url='https://console.example.org', trust_env=False) as anonymous:
                    assert (await anonymous.get(route + '/' + key)).status_code == 401
                return key, slow_key
        passed_id, failed_id = asyncio.run(exercise())
        with sqlite3.connect(path) as db:
            assert db.execute('SELECT outcome FROM verification_results WHERE request_id=?',
                              (passed_id,)).fetchone() == ('passed',)
            assert db.execute('SELECT outcome FROM verification_results WHERE request_id=?',
                              (failed_id,)).fetchone() == ('failed',)
            assert db.execute('SELECT count(*) FROM verification_attestations').fetchone() == (2,)
            assert db.execute('SELECT count(*) FROM release_records').fetchone() == (2,)
            assert db.execute('SELECT count(*) FROM content_bindings').fetchone() == (2,)
            assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        engine.dispose()
    finally:
        get_settings.cache_clear()
        if process.poll() is None:
            process.terminate()
        try:
            process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)
        assert process.returncode is not None
        for label in ('atom.verifier.owner=api-route-worker',
                      'atom.verifier-coordinator-lease.owner'):
            inventory = subprocess.run(['docker','ps','-aq','--filter',f'label={label}'],
                                       capture_output=True, text=True, check=True)
            assert inventory.stdout.strip() == ''
