"""Built snapshot UI against real owner-scoped routes and a v16 ledger.

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
from playwright.sync_api import sync_playwright, expect
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
def test_snapshot_publish_restore_withdraw_and_lost_response(
        http_history, tmp_path, monkeypatch, viewport, built_dist):
    from test_adoption_repository import snapshot
    from app.release_view import materialized_release
    from app.bounded_operations import BoundedOperations
    from app.content_access import ContentAccessRepository
    from app.content_bootstrap import ContentNavigation
    from app.content_hosts import ContentHosts
    from app.content_repository import ContentRepository
    from app.content_service import ContentService
    from app.routers import content_access
    from urllib.parse import urlsplit
    from integration.test_release_stream_browser import _certificate, _serve_https
    path, original_store, intent, source, displaced = http_history
    for version in (14, 15, 16):
        migrate(path, tmp_path / f'before-browser-{version}.db', target_version=version)
    # Storage transport is a fixture; all bytes, registration, API transactions and browser interactions are real.
    payload, artifact = snapshot(b'<html><body>Second published version</body></html>')
    payloads = {original_store.key: original_store.payload, artifact.key: payload}
    store = SimpleNamespace(read=lambda key: payloads[key])
    app, token, engine = _configured_api(path, store, intent, tmp_path, monkeypatch)
    monkeypatch.setenv('ATOM_PUBLICATION_VERIFICATION', 'advisory')
    verifier_values = {name: os.environ[name] for name in ('ATOM_VERIFIER_ORIGIN', 'ATOM_VERIFIER_CONTROL_TOKEN', 'ATOM_VERIFIER_POLICY_DIGEST', 'ATOM_VERIFIER_RUNNER_VERSION')}
    for name in verifier_values:
        monkeypatch.delenv(name)
    get_settings.cache_clear()
    app.state.execution = SimpleNamespace(store=store, repository=RevisionRepository(path))
    app.state.verifier_client = None
    app.include_router(auth.router, prefix='/api')
    app.include_router(projects.router, prefix='/api')
    app.include_router(verifications.router, prefix='/api')
    app.include_router(content_access.router, prefix='/api')
    app.state.content_issuer = BoundedOperations(capacity=2)
    _static(app, built_dist)
    outer = FastAPI()
    outer.mount('/atom', app)
    server, thread, port = _serve(outer)
    content_app = ContentService(ContentRepository(path), store, ContentHosts('apps.example.net'),
        access=ContentAccessRepository(path), navigation=ContentNavigation(ORIGIN, '/atom'))
    content_responses = []
    async def observed_content(scope, receive, send):
        if scope['type'] == 'http':
            headers = dict(scope['headers'])
            if headers.get(b'host') == b'console.example.org':
                await outer(scope, receive, send)
                return
            assert b'__Host-atom_console' not in headers.get(b'cookie', b'')
            async def observed_send(message):
                if message['type'] == 'http.response.start':
                    content_responses.append((message['status'], scope['path']))
                await send(message)
            await content_app(scope, receive, observed_send)
        else:
            await content_app(scope, receive, send)
    key, cert = _certificate(tmp_path)
    content_server, content_thread, content_listener, _ = _serve_https(observed_content, key, cert)
    failures, responses = [], []
    drop = [False]
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(args=['--host-resolver-rules=MAP *.apps.example.net 127.0.0.1, MAP console.example.org 127.0.0.1', '--no-proxy-server'])
            context = browser.new_context(viewport=viewport, service_workers='block', ignore_https_errors=True)
            context.add_cookies([{'name':'__Host-atom_console', 'value':token,
                'url':ORIGIN, 'secure':True, 'httpOnly':True, 'sameSite':'Lax'}])
            def bridge(route):
                request = route.request
                if '/events?' in request.url:
                    route.abort('blockedbyclient')
                    return
                headers = request.headers | {'host':'console.example.org', 'x-forwarded-proto':'https', 'accept-encoding':'identity'}
                response = route.fetch(url=f'http://127.0.0.1:{port}' + request.url[len(ORIGIN):], headers=headers, timeout=10000)
                if drop[0] and request.method == 'POST' and request.url.endswith('/unpublish'):
                    drop[0] = False
                    assert response.status == 200
                    route.abort('failed')
                    return
                route.fulfill(status=response.status, headers={key:value for key,value in response.headers.items()
                    if key.lower() not in ('content-encoding','content-length','transfer-encoding')}, body=response.body())
            context.route(ORIGIN + '/atom/**', bridge)
            page = context.new_page()
            page.on('pageerror', lambda error: failures.append(str(error)))
            page.on('response', lambda response: responses.append((response.status,response.url)))
            def open_release():
                page.goto(ORIGIN + '/atom/app/p/project', wait_until='domcontentloaded')
                page.get_by_role('tab', name='发布', exact=True).click()
                panel = page.get_by_label('发布与历史', exact=True)
                panel.get_by_role('heading', name='当前已发布', exact=True).wait_for()
                return panel
            panel = open_release()
            assert panel.get_by_role('button', name='发布更新', exact=True).is_enabled()
            assert not any('/verifications/' in url for _,url in responses)
            assert panel.get_by_text(displaced.release_id, exact=True).count() == 0
            assert panel.get_by_label('发布历史').get_by_role('listitem').count() == 2
            assert page.get_by_label('对话').is_hidden() == (viewport['width'] < 768)
            # Register distinct new draft bytes through the revision repository.
            with sqlite3.connect(path) as db:
                db.execute("UPDATE projects SET active_run_id='run' WHERE id='project'")
            revisions = RevisionRepository(path)
            workspace = revisions.find_workspace('user', 'project', None)
            revisions.reserve('user', workspace, 'run', 'browser-new-revision', 'browser-grant', int(time.time()) + 120)
            revisions.bind('user', 'browser-new-revision', 'browser-container')
            newer = revisions.register('user', 'browser-new-revision', 'browser-container', 'browser-grant', artifact)
            revisions.observe_termination('user', 'browser-new-revision', confirmed=True, outcome='succeeded')
            with sqlite3.connect(path) as db:
                db.execute("UPDATE projects SET active_run_id=NULL,status='ready' WHERE id='project'")
            panel = open_release()
            panel.get_by_text('你有尚未发布的编辑。', exact=False).wait_for()
            # Explicit strict policy still blocks the new unverified revision.
            for name, value in verifier_values.items():
                monkeypatch.setenv(name, value)
            monkeypatch.setenv('ATOM_PUBLICATION_VERIFICATION', 'required')
            get_settings.cache_clear()
            app.state.verifier_client = object()
            panel.get_by_role('button', name='刷新', exact=True).click()
            panel.get_by_text('此项目启用了发布前检查', exact=False).wait_for()
            assert panel.get_by_role('button', name='发布更新', exact=True).is_disabled()
            app.state.verifier_client = None
            panel.get_by_role('button', name='刷新', exact=True).click()
            panel.get_by_text('暂时无法读取发布状态：', exact=False).wait_for()
            assert panel.get_by_label('发布操作').count() == 0
            monkeypatch.setenv('ATOM_PUBLICATION_VERIFICATION', 'advisory')
            for name in verifier_values:
                monkeypatch.delenv(name)
            get_settings.cache_clear()
            panel.get_by_role('button', name='刷新', exact=True).click()
            panel.get_by_text('功能检查可按需运行', exact=False).wait_for()
            panel.get_by_role('button', name='发布更新', exact=True).click()
            panel.get_by_text('当前编辑与已发布版本一致。', exact=False).wait_for()
            repository = ReleaseRepository(path)
            current = repository.current(owner='user', project_id='project')
            assert current.revision_id == newer.revision_id and current.verification_id is None
            with materialized_release(repository, store, slug=intent['slug']) as view:
                assert (view.path / 'index.html').read_bytes() == b'<html><body>Second published version</body></html>'
            anonymous = browser.new_context(ignore_https_errors=True, service_workers='block')
            public_page = anonymous.new_page()
            public_url = ContentHosts('apps.example.net').url(current.binding_id)
            assert public_page.goto(public_url).status == 200
            public_page.get_by_text('Second published version', exact=True).wait_for()
            assert public_page.evaluate("localStorage.setItem('preview-check','ok'); localStorage.getItem('preview-check')") == 'ok'
            assert not any(cookie['name'] == '__Host-atom_console' for cookie in anonymous.cookies())
            panel.get_by_role('button', name='恢复此版本').first.click()
            panel.get_by_role('button', name='确认恢复', exact=True).click()
            panel.get_by_text('你有尚未发布的编辑。', exact=False).wait_for()
            restored = repository.current(owner='user', project_id='project')
            assert restored.revision_id == displaced.revision_id
            assert revisions.current_revision('user', workspace).revision_id == newer.revision_id
            with materialized_release(repository, store, slug=intent['slug']) as view:
                assert (view.path / 'index.html').read_bytes() == b'<html>heat</html>'
            drop[0] = True
            panel.get_by_role('button', name='停止发布', exact=True).click()
            panel.get_by_role('button', name='确认停止发布', exact=True).click()
            panel.get_by_text('结果暂时无法确认：', exact=False).wait_for()
            assert repository.current(owner='user', project_id='project').live is False
            generation = repository.current(owner='user', project_id='project').generation
            page.reload(wait_until='domcontentloaded')
            page.get_by_role('tab', name='发布', exact=True).click()
            panel.get_by_role('button', name='重试本次操作', exact=True).click()
            panel.get_by_role('heading', name='网站已停止发布', exact=True).wait_for()
            assert repository.current(owner='user', project_id='project').generation == generation
            assert public_page.goto(public_url).status == 404
            anonymous.close()
            expect(panel.get_by_label('发布历史').get_by_role('listitem')).to_have_count(4)
            assert all(link.get_attribute('href').endswith('/_atom/bootstrap') for link in panel.get_by_role('link', name='预览', exact=True).all())
            with context.expect_page() as opened:
                panel.get_by_role('link', name='预览', exact=True).first.click()
            preview = opened.value
            try:
                preview.get_by_role('button', name='确认并打开', exact=True).click(timeout=10000)
            except Exception:
                pytest.fail(f'Preview navigation failed: {urlsplit(preview.url).path}; '
                            f'{content_responses}; {preview.locator("body").inner_text()[:700]}')
            preview.wait_for_url(re.compile(r'https://r-[0-9a-f]{32}\.apps\.example\.net/'))
            preview.get_by_text('heat', exact=True).wait_for()
            assert preview.evaluate('document.cookie') == ''
            preview.close()
            # A read failure must not look like an empty publication, or expose actions.
            live_execution = app.state.execution
            app.state.execution = None
            panel.get_by_role('button', name='刷新', exact=True).click()
            panel.get_by_text('暂时无法读取发布状态：', exact=False).wait_for()
            assert panel.get_by_label('发布操作').count() == 0
            app.state.execution = live_execution
            panel.get_by_role('button', name='刷新', exact=True).click()
            panel.get_by_role('heading', name='网站已停止发布', exact=True).wait_for()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert not failures, failures
            page.screenshot(path=str(tmp_path / f'snapshots-{viewport["width"]}.png'), full_page=True)
            context.close()
            browser.close()
    finally:
        content_server.should_exit = True
        content_thread.join(timeout=5)
        content_listener.close()
        server.should_exit = True
        thread.join(timeout=5)
        engine.dispose()
        get_settings.cache_clear()
