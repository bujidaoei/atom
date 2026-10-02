"""Built workbench → private verifier → real Chromium → v15 release ledger.

This is an isolated target-Linux acceptance path. It does not route public
traffic or mutate the schema10 production databases.
"""
from contextlib import asynccontextmanager
import faulthandler
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

from fastapi import FastAPI
import httpx
from playwright.sync_api import sync_playwright
import pytest

from app.artifacts import ArtifactStore
from app.config import get_settings
from app.migrations import migrate
from app.release_repository import ReleaseRepository
from app.revisions import RevisionRepository
from app.routers import auth, projects, verifications
from app.verification_repository import VerificationRepository
from app.verifier_client import VerifierClient
from test_adoption_repository import prepared, snapshot
from test_adoption_verification_repository import adopted
from test_release_workbench_browser import ORIGIN, _serve, _static
from test_revision_migrations import legacy
from test_rollback_v14_api import _configured_api


IMAGE = os.environ.get('ATOM_VERIFIER_TEST_IMAGE_DIGEST')
ROOT = Path(__file__).resolve().parents[3]
PROFILE = ROOT / 'deploy' / 'verifier-seccomp.json'
DIST = Path('/usr/share/nginx/html')
pytestmark = pytest.mark.skipif(
    sys.platform != 'linux' or not IMAGE or not os.environ.get('ATOM_VERIFIER_TEST_REAL_STORE'),
    reason='requires target Linux daemon, pinned Chromium and host-visible scratch')


def _port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


@pytest.mark.parametrize('viewport', [
    pytest.param({'width': 1280, 'height': 800}, id='desktop'),
    pytest.param({'width': 390, 'height': 844}, id='mobile'),
])
def test_ui_runs_real_private_verification_and_publishes(
        adopted, tmp_path, monkeypatch, viewport):
    faulthandler.dump_traceback_later(35, file=sys.stderr)
    def stage(name):
        print(f'verifier-browser-{viewport["width"]}: {name}', flush=True)

    stage('fixture-ready')
    assert DIST.joinpath('index.html').is_file(), 'built /atom/ SPA required'
    assert PROFILE.is_file(), 'host-visible pinned seccomp profile required'
    path, receipt, intent = adopted
    with sqlite3.connect(path) as db:
        db.execute('UPDATE requirements SET checks_json=? WHERE project_id=?',
                   (json.dumps([{'type': 'exists', 'selector': 'body'}]), 'project'))
    migrate(path, tmp_path / 'before-ui-v13.db', target_version=13)
    migrate(path, tmp_path / 'before-ui-v14.db', target_version=14)
    migrate(path, tmp_path / 'before-ui-v15.db', target_version=15)
    payload, artifact = snapshot(b'<html>heat</html>')
    assert artifact == receipt.artifact
    root = tmp_path / 'artifacts'
    root.mkdir(mode=0o700)
    store = ArtifactStore(root)
    assert store.put(payload) == artifact

    app, owner_token, engine = _configured_api(path, store, intent, tmp_path, monkeypatch)
    app.state.execution = SimpleNamespace(store=store, repository=RevisionRepository(path))
    app.include_router(auth.router, prefix='/api')
    app.include_router(projects.router, prefix='/api')
    app.include_router(verifications.router, prefix='/api')
    _static(app, DIST)
    outer = FastAPI()
    outer.mount('/atom', app)

    port = _port()
    control_token = os.environ['ATOM_VERIFIER_CONTROL_TOKEN']
    monkeypatch.setenv('ATOM_VERIFIER_ORIGIN', f'http://127.0.0.1:{port}')
    get_settings.cache_clear()
    verifier_id = f'ui-acceptance-{viewport["width"]}'
    environment = dict(os.environ, ATOM_VERIFIER_DB_PATH=str(path),
        ATOM_VERIFIER_ARTIFACT_DIR=str(root), ATOM_VERIFIER_IMAGE=IMAGE,
        ATOM_VERIFIER_SECCOMP_PATH=str(PROFILE), ATOM_VERIFIER_ID=verifier_id,
        ATOM_VERIFIER_CONTROL_TOKEN=control_token)
    verifier = subprocess.Popen([sys.executable, '-m', 'uvicorn',
        'app.verifier_service:create_app', '--factory', '--host', '127.0.0.1',
        '--port', str(port), '--log-level', 'error'], env=environment,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    stage('verifier-started')
    server = thread = None
    failures = []
    responses = []
    requests = []
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', trust_env=False,
                          timeout=2) as probe:
            deadline = time.monotonic() + 20
            while True:
                assert verifier.poll() is None, 'private verifier failed startup'
                try:
                    assert probe.get('/health').json() == {'ok': True}
                    break
                except httpx.ConnectError:
                    assert time.monotonic() < deadline, 'private verifier not ready'
                    time.sleep(.05)
        stage('verifier-healthy')

        @asynccontextmanager
        async def trusted_client(_app):
            async with VerifierClient(f'http://127.0.0.1:{port}', control_token) as client:
                await client.require_ready()
                app.state.verifier_client = client
                yield
                app.state.verifier_client = None

        outer.router.lifespan_context = trusted_client
        server, thread, api_port = _serve(outer)
        stage('api-started')
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='chromium', headless=False,
                                                 dumpio=True)
            stage('browser-started')
            context = browser.new_context(viewport=viewport, service_workers='block')
            context.add_cookies([{'name': '__Host-atom_console', 'value': owner_token,
                'url': ORIGIN, 'secure': True, 'httpOnly': True, 'sameSite': 'Lax'}])

            def bridge(route):
                request = route.request
                requests.append(request.url)
                stage('route-start-' + request.url.split('/atom/', 1)[-1][:80])
                assert request.url.startswith(ORIGIN + '/atom/')
                if '/events?' in request.url:
                    route.abort('blockedbyclient')
                    return
                if request.url.startswith(ORIGIN + '/atom/assets/'):
                    relative = request.url.removeprefix(ORIGIN + '/atom/')
                    asset = (DIST / relative).resolve()
                    assert asset.is_relative_to(DIST.resolve()) and asset.is_file()
                    route.fulfill(path=str(asset))
                    stage('asset-fulfilled')
                    return
                headers = request.headers | {'host': 'console.example.org',
                    'x-forwarded-proto': 'https', 'accept-encoding': 'identity'}
                response = route.fetch(url=f'http://127.0.0.1:{api_port}' +
                    request.url[len(ORIGIN):], headers=headers, timeout=10000)
                stage('route-end-' + str(response.status))
                route.fulfill(status=response.status,
                    headers={key: value for key, value in response.headers.items()
                        if key.lower() not in ('content-encoding', 'content-length',
                                               'transfer-encoding')},
                    body=response.body())

            context.route(ORIGIN + '/atom/**', bridge)
            page = context.new_page()
            stage('page-created')
            page.on('pageerror', lambda error: failures.append(str(error)))
            page.on('console', lambda message: failures.append(message.text)
                    if message.type == 'error' else None)
            page.on('requestfailed', lambda request: failures.append(
                'request_failed: ' + request.url + ' ' + str(request.failure)))
            page.on('response', lambda response: responses.append((response.status, response.url)))
            page.on('response', lambda response: stage('response-type-' +
                str(response.status) + '-' + str(response.header_value('content-type'))))
            try:
                page.goto(ORIGIN + '/atom/app/p/project', wait_until='domcontentloaded',
                          timeout=15000)
            except Exception as error:
                raise AssertionError((type(error).__name__, requests, responses, failures)) from error
            stage('page-loaded')
            try:
                page.get_by_role('tab', name='发布', exact=True).wait_for(timeout=8000)
            except Exception:
                state = page.evaluate('''() => ({ ready: document.readyState,
                    root: document.getElementById('root')?.innerHTML.slice(0, 500),
                    module: document.querySelector('script[type="module"]')?.outerHTML })''')
                stage('tab-missing ' + repr((page.url, requests, responses, failures, state)))
                context.close()
                browser.close()
                raise
            page.get_by_role('tab', name='发布', exact=True).click()
            stage('release-tab-open')
            panel = page.get_by_label('发布工作台')
            controls = panel.get_by_label('可信发布操作')
            controls.get_by_role('button', name='预约当前修订验证').click()
            controls.get_by_role('button', name='执行已预约验证').wait_for()
            reserved = VerificationRepository(path).latest(owner='user', project_id='project')
            assert reserved is not None and reserved.result is None
            controls.get_by_role('button', name='执行已预约验证').click()
            controls.get_by_text('当前修订已有完整通过的可信验证。').wait_for(timeout=60000)
            result = VerificationRepository(path).latest(owner='user', project_id='project')
            assert result is not None and result.request.id == reserved.request.id
            assert result.result is not None and result.result.outcome == 'passed'
            with sqlite3.connect(path) as db:
                assert db.execute('SELECT count(*) FROM verification_attestations '
                                  'WHERE request_id=?', (reserved.request.id,)).fetchone() == (1,)

            controls.get_by_role('combobox', name='发布受众').select_option('public')
            controls.get_by_role('textbox', name='发布短链接').fill('verified-ui-site')
            controls.get_by_role('checkbox').first.check()
            controls.get_by_role('button', name='发布经验证版本').click()
            panel.get_by_role('heading', name='线上版本', exact=True).wait_for()
            publication = ReleaseRepository(path).current(owner='user', project_id='project')
            assert publication is not None and publication.live
            assert publication.verification_id == reserved.request.id
            assert publication.audience == 'public' and publication.slug == 'verified-ui-site'
            page.reload(wait_until='domcontentloaded')
            page.get_by_role('tab', name='发布', exact=True).click()
            page.get_by_label('发布工作台').get_by_text(publication.release_id, exact=True).wait_for()
            assert (200, ORIGIN + '/atom/api/projects/project/verifications/' +
                    reserved.request.id + '/run') in responses
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert not failures, failures
            page.screenshot(path=str(tmp_path / f'verifier-ui-{viewport["width"]}.png'),
                            full_page=True)
            context.close()
            browser.close()
    finally:
        faulthandler.cancel_dump_traceback_later()
        if server is not None:
            server.should_exit = True
            thread.join(timeout=10)
            assert not thread.is_alive(), 'API browser server did not stop'
        if verifier.poll() is None:
            verifier.terminate()
        try:
            verifier.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            verifier.kill()
            verifier.communicate(timeout=5)
        assert verifier.returncode is not None
        for label in (f'atom.verifier.owner={verifier_id}',
                      'atom.verifier-coordinator-lease.owner'):
            inventory = subprocess.run(['docker', 'ps', '-aq', '--filter', f'label={label}'],
                                       capture_output=True, text=True, check=True)
            assert inventory.stdout.strip() == ''
        engine.dispose()
        get_settings.cache_clear()
