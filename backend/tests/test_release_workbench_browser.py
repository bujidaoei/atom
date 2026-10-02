"""Built release workbench against real owner-scoped routes and a v15 ledger.

The browser's test-only HTTPS origin is forwarded to isolated loopback Uvicorn.
This deliberately tests the UI/API composition, not deployment TLS or ingress.
"""

from pathlib import Path
import re
from threading import Thread
from types import SimpleNamespace
import os
import shutil
import socket
import sqlite3
import subprocess
import time

from fastapi import FastAPI
from fastapi.responses import FileResponse
from playwright.sync_api import sync_playwright
import pytest
import uvicorn

from app.migrations import migrate
from app.revisions import RevisionRepository
from app.release_repository import ReleaseRepository
from app.verification_repository import VerificationRepository
from app.routers import auth, projects, verifications
from app.config import get_settings
from test_revision_migrations import legacy
from test_adoption_repository import prepared
from test_adoption_verification_repository import adopted
from test_rollback_v14_api import _configured_api, http_history


ROOT = Path(__file__).resolve().parents[2]
ORIGIN = 'https://console.example.org'


@pytest.fixture(scope='module')
def built_dist():
    frontend = ROOT / 'frontend'
    local_dist = frontend / 'dist'
    image_dist = Path('/usr/share/nginx/html')
    npm = shutil.which('npm')
    if (frontend / 'node_modules').is_dir() and npm:
        subprocess.run([npm, '--prefix', str(frontend), 'run', 'build'],
            env=os.environ | {'VITE_BASE': '/atom/'}, check=True, timeout=180,
            capture_output=True, text=True, encoding='utf-8', errors='replace')
        dist = local_dist
    elif image_dist.is_dir():
        dist = image_dist
    else:
        pytest.fail('built SPA unavailable: install frontend dependencies and run VITE_BASE=/atom/ npm run build')
    assert '/atom/assets/' in (dist / 'index.html').read_text('utf-8')
    return dist


def _serve(app):
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port,
        log_level='error', access_log=False, proxy_headers=True,
        forwarded_allow_ips='127.0.0.1'))
    thread = Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert thread.is_alive() and time.monotonic() < deadline, 'loopback API did not start'
        time.sleep(.02)
    return server, thread, port


def _static(app, dist):
    @app.get('/{path:path}')
    def built_spa(path: str):
        candidate = (dist / path).resolve()
        if candidate.is_file() and candidate.is_relative_to(dist.resolve()):
            return FileResponse(candidate)
        return FileResponse(dist / 'index.html')


@pytest.mark.parametrize('viewport', [
    pytest.param({'width': 1280, 'height': 800}, id='desktop'),
    pytest.param({'width': 390, 'height': 844}, id='mobile'),
])
def test_release_workbench_real_routes_and_ledger(
        http_history, tmp_path, monkeypatch, viewport, built_dist):
    path, store, intent, _source, displaced = http_history
    migrate(path, tmp_path / 'before-browser-v14.db', target_version=14)
    migrate(path, tmp_path / 'before-browser-v15.db', target_version=15)
    app, token, engine = _configured_api(path, store, intent, tmp_path, monkeypatch)
    app.state.execution = SimpleNamespace(store=store, repository=RevisionRepository(path))
    app.state.verifier_client = object()
    app.include_router(auth.router, prefix='/api')
    app.include_router(projects.router, prefix='/api')
    app.include_router(verifications.router, prefix='/api')
    _static(app, built_dist)
    outer = FastAPI()
    outer.mount('/atom', app)
    server, thread, port = _serve(outer)
    failures = []
    responses = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(viewport=viewport, service_workers='block')
            context.add_cookies([{'name': '__Host-atom_console', 'value': token,
                'url': ORIGIN, 'secure': True, 'httpOnly': True, 'sameSite': 'Lax'}])

            def bridge(route):
                request = route.request
                assert request.url.startswith(ORIGIN + '/atom/')
                if '/events?' in request.url:
                    route.abort('blockedbyclient')
                    return
                headers = request.headers | {'host': 'console.example.org',
                    'x-forwarded-proto': 'https', 'accept-encoding': 'identity'}
                response = route.fetch(url=f'http://127.0.0.1:{port}' + request.url[len(ORIGIN):],
                    headers=headers, timeout=10000)
                route.fulfill(status=response.status,
                    headers={key: value for key, value in response.headers.items()
                        if key.lower() not in ('content-encoding', 'content-length', 'transfer-encoding')},
                    body=response.body())

            context.route('https://console.example.org/atom/**', bridge)
            page = context.new_page()
            page.on('pageerror', lambda error: failures.append(str(error)))
            page.on('response', lambda response: responses.append((response.status, response.url)))
            page.goto(ORIGIN + '/atom/app/p/project', wait_until='domcontentloaded')
            page.get_by_role('tab', name='发布', exact=True).click()
            panel = page.get_by_label('发布工作台')
            panel.get_by_text('最近一次可信验证').wait_for()
            bounds = panel.bounding_box()
            assert bounds is not None and bounds['y'] < viewport['height'] / 2
            assert page.get_by_label('对话').is_hidden() == (viewport['width'] < 768)
            panel.get_by_role('heading', name='线上版本', exact=True).wait_for()
            panel.get_by_text('passed', exact=False).first.wait_for()
            assert panel.get_by_text('passed', exact=False).count() >= 1
            assert panel.get_by_text(displaced.release_id, exact=True).count() == 1
            assert panel.get_by_text('暂无已登记的发布指针').count() == 0
            for suffix in ('/api/auth/me', '/api/projects/project',
                           '/api/projects/project/releases/current',
                           '/api/projects/project/verifications/latest'):
                assert (200, ORIGIN + '/atom' + suffix) in responses, suffix
            page.reload(wait_until='domcontentloaded')
            page.get_by_role('tab', name='发布', exact=True).click()
            page.get_by_label('发布工作台').get_by_text(displaced.release_id, exact=True).wait_for()

            app.state.verifier_client = None
            panel.get_by_role('button', name='刷新状态').click()
            panel.get_by_text('验证状态无法确认：', exact=False).wait_for()
            assert panel.get_by_text('当前项目没有验证记录').count() == 0
            assert panel.get_by_label('可信发布操作').count() == 0
            app.state.verifier_client = object()

            live_execution = app.state.execution
            app.state.execution = None
            panel.get_by_role('button', name='刷新状态').click()
            panel.get_by_text('发布状态无法确认：', exact=False).wait_for()
            assert panel.get_by_text('暂无已登记的发布指针').count() == 0
            assert panel.get_by_label('可信发布操作').count() == 0
            app.state.execution = live_execution

            verifier_keys = ('ATOM_VERIFIER_ORIGIN', 'ATOM_VERIFIER_CONTROL_TOKEN',
                'ATOM_VERIFIER_POLICY_DIGEST', 'ATOM_VERIFIER_RUNNER_VERSION')
            verifier_settings = {key: os.environ[key] for key in verifier_keys}
            for key in verifier_keys:
                monkeypatch.delenv(key)
            get_settings.cache_clear()
            panel.get_by_role('button', name='刷新状态').click()
            panel.get_by_text('可信验证服务尚未启用。').wait_for()
            panel.get_by_text('可信发布尚未启用').wait_for()
            assert panel.get_by_label('可信发布操作').count() == 0
            for key, value in verifier_settings.items():
                monkeypatch.setenv(key, value)
            get_settings.cache_clear()

            with sqlite3.connect(path) as db:
                db.execute("UPDATE projects SET active_run_id='run' WHERE id='project'")
            revisions = RevisionRepository(path)
            workspace = revisions.find_workspace('user', 'project', None)
            current = revisions.current_revision('user', workspace)
            revisions.reserve('user', workspace, 'run', 'browser-new-revision',
                'browser-grant', int(time.time()) + 120)
            revisions.bind('user', 'browser-new-revision', 'browser-container')
            newer = revisions.register('user', 'browser-new-revision', 'browser-container',
                'browser-grant', current.artifact)
            assert newer.revision_id != displaced.revision_id
            page.reload(wait_until='domcontentloaded')
            page.get_by_role('tab', name='发布', exact=True).click()
            panel = page.get_by_label('发布工作台')
            panel.get_by_text('当前修订与线上版本不同。', exact=False).wait_for()
            panel.get_by_text('该验证属于旧修订', exact=False).wait_for()
            assert panel.get_by_text(displaced.release_id, exact=True).count() == 1
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert not failures, failures
            page.screenshot(path=str(tmp_path / f'workbench-{viewport["width"]}.png'), full_page=True)
            context.close()
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        engine.dispose()
        get_settings.cache_clear()


@pytest.mark.parametrize('viewport', [
    pytest.param({'width': 1280, 'height': 800}, id='desktop'),
    pytest.param({'width': 390, 'height': 844}, id='mobile'),
])
def test_release_workbench_real_withdraw_publish_and_lost_response(
        http_history, tmp_path, monkeypatch, viewport, built_dist):
    path, store, intent, _source, displaced = http_history
    migrate(path, tmp_path / 'before-control-v14.db', target_version=14)
    migrate(path, tmp_path / 'before-control-v15.db', target_version=15)
    app, token, engine = _configured_api(path, store, intent, tmp_path, monkeypatch)
    app.state.execution = SimpleNamespace(store=store, repository=RevisionRepository(path))
    app.state.verifier_client = object()
    app.include_router(auth.router, prefix='/api')
    app.include_router(projects.router, prefix='/api')
    app.include_router(verifications.router, prefix='/api')
    _static(app, built_dist)
    outer = FastAPI()
    outer.mount('/atom', app)
    server, thread, port = _serve(outer)
    failures = []
    dropped = [False]
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(viewport=viewport, service_workers='block')
            context.add_cookies([{'name': '__Host-atom_console', 'value': token,
                'url': ORIGIN, 'secure': True, 'httpOnly': True, 'sameSite': 'Lax'}])

            def bridge(route):
                request = route.request
                if '/events?' in request.url:
                    route.abort('blockedbyclient')
                    return
                headers = request.headers | {'host': 'console.example.org',
                    'x-forwarded-proto': 'https', 'accept-encoding': 'identity'}
                response = route.fetch(url=f'http://127.0.0.1:{port}' + request.url[len(ORIGIN):],
                    headers=headers, timeout=10000)
                if dropped[0] and request.method == 'POST' and request.url.endswith('/unpublish'):
                    dropped[0] = False
                    assert response.status == 200
                    route.abort('failed')
                    return
                route.fulfill(status=response.status,
                    headers={key: value for key, value in response.headers.items()
                        if key.lower() not in ('content-encoding', 'content-length', 'transfer-encoding')},
                    body=response.body())

            context.route('https://console.example.org/atom/**', bridge)
            page = context.new_page()
            page.on('pageerror', lambda error: failures.append(str(error)))
            page.goto(ORIGIN + '/atom/app/p/project', wait_until='domcontentloaded')
            page.get_by_role('tab', name='发布', exact=True).click()
            panel = page.get_by_label('发布工作台')
            controls = panel.get_by_label('可信发布操作')
            controls.get_by_text('当前修订已有完整通过的可信验证。').wait_for()
            controls.get_by_role('button', name='更新可信发布').is_disabled()

            controls.get_by_role('checkbox').last.check()
            controls.get_by_role('button', name='撤回线上版本').click()
            panel.get_by_role('heading', name='已撤回的版本').wait_for()
            assert ReleaseRepository(path).current(owner='user', project_id='project').live is False

            controls = panel.get_by_label('可信发布操作')
            controls.get_by_role('combobox', name='发布受众').select_option('public')
            assert controls.get_by_role('textbox', name='发布短链接').input_value() == 'trusted-site'
            assert controls.get_by_role('textbox', name='发布短链接').is_disabled()
            controls.get_by_role('checkbox').first.check()
            controls.get_by_role('button', name='发布经验证版本').click()
            panel.get_by_role('heading', name='线上版本', exact=True).wait_for()
            panel.get_by_role('link', name=re.compile('公开分享地址')).wait_for()
            current = ReleaseRepository(path).current(owner='user', project_id='project')
            assert current is not None and current.live and current.generation == displaced.generation + 2
            assert current.audience == 'public' and current.slug == 'trusted-site'
            assert current.release_id != displaced.release_id

            page.reload(wait_until='domcontentloaded')
            page.get_by_role('tab', name='发布', exact=True).click()
            panel = page.get_by_label('发布工作台')
            panel.get_by_text(current.release_id, exact=True).wait_for()
            controls = panel.get_by_label('可信发布操作')
            dropped[0] = True
            controls.get_by_role('checkbox').last.check()
            controls.get_by_role('button', name='撤回线上版本').click()
            controls.get_by_text('命令尚未确认', exact=False).wait_for()
            deadline = time.monotonic() + 5
            while ReleaseRepository(path).current(owner='user', project_id='project').live:
                assert time.monotonic() < deadline, 'withdrawal did not commit before response loss'
                time.sleep(0.02)
            assert ReleaseRepository(path).current(owner='user', project_id='project').live is False
            controls.get_by_role('button', name='查询账本').click()
            panel.get_by_role('heading', name='已撤回的版本').wait_for()
            assert panel.get_by_role('button', name='查询账本').count() == 0

            controls.get_by_role('button', name='预约当前修订验证').click()
            controls.get_by_role('button', name='执行已预约验证').wait_for()
            reserved = VerificationRepository(path).latest(owner='user', project_id='project')
            assert reserved is not None and reserved.result is None and not reserved.dispatched
            page.reload(wait_until='domcontentloaded')
            page.get_by_role('tab', name='发布', exact=True).click()
            controls = page.get_by_label('可信发布操作')
            controls.get_by_role('button', name='执行已预约验证').wait_for()
            page.evaluate("sessionStorage.setItem('atom.release.pending.project', '{broken')")
            page.reload(wait_until='domcontentloaded')
            page.get_by_role('tab', name='发布', exact=True).click()
            controls = page.get_by_label('可信发布操作')
            controls.get_by_text('操作已锁定', exact=False).wait_for()
            assert controls.get_by_role('button', name='执行已预约验证').is_disabled()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert not failures, failures
            page.screenshot(path=str(tmp_path / f'control-{viewport["width"]}.png'), full_page=True)
            context.close()
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        engine.dispose()
        get_settings.cache_clear()
