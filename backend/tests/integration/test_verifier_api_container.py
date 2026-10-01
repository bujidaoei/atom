"""Authenticated v13 console route through private Uvicorn and real Chromium."""
import asyncio
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
import time

from fastapi import FastAPI
import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.artifacts import ArtifactStore
from app.config import get_settings
from app.db import get_db
from app.migrations import migrate
from app.routers import verifications
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
                    result = await client.post(route + '/' + key + '/run',
                                               headers=intent_headers)
                    assert result.status_code == 200, result.text
                    assert result.json()['state'] == 'passed'
                    assert result.json()['total'] == result.json()['passed'] == 1
                    settled = await client.get(route + '/' + key)
                    assert settled.status_code == 200 and settled.json() == result.json()
                    repeat = await client.post(route + '/' + key + '/run',
                                               headers=intent_headers)
                    assert repeat.status_code == 200 and repeat.json() == result.json()
                    foreign = await client.get('/api/projects/other/verifications/' + key)
                    assert foreign.status_code == 404
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api),
                    base_url='https://console.example.org', trust_env=False) as anonymous:
                    assert (await anonymous.get(route + '/' + key)).status_code == 401
        asyncio.run(exercise())
        with sqlite3.connect(path) as db:
            assert db.execute('SELECT outcome FROM verification_results').fetchone() == ('passed',)
            assert db.execute('SELECT count(*) FROM verification_attestations').fetchone() == (1,)
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
