"""Built workspace opens the exact saved revision on an isolated IP TLS port."""
from types import SimpleNamespace
import socket

from fastapi import FastAPI
from playwright.sync_api import sync_playwright
import pytest

from app.bounded_operations import BoundedOperations
from app.config import get_settings
from app.console_auth import proof_for_new_session
from app.content_repository import ContentRepository
from app.content_service import ContentService
from app.migrations import migrate
from app.preview_access import PreviewAccessRepository
from app.preview_service import PreviewService
from app.project_origins import ProjectOriginRepository
from app.project_port_hosts import ProjectPortHosts
from app.project_public_hosts import ProjectPublicHosts
from app.revisions import RevisionRepository
from app.routers import auth, preview_access, projects, verifications
from test_ip_preview_browser_v18 import _adjacent_listeners, _start, _tls_files
from test_release_workbench_browser import _serve, _static, built_dist
from test_rollback_v14_api import _configured_api, http_history
from test_adoption_verification_repository import adopted
from test_adoption_repository import prepared
from test_revision_migrations import legacy


@pytest.mark.parametrize('browser_name', ('chromium', 'firefox'))
def test_workspace_opens_isolated_saved_preview(
        http_history, tmp_path, monkeypatch, built_dist, browser_name):
    path, store, intent, _source, _displaced = http_history
    for version in range(14, 19):
        migrate(path, tmp_path / f'before-workspace-v{version}.db', target_version=version)
    app, token, engine = _configured_api(path, store, intent, tmp_path, monkeypatch)
    listeners = _adjacent_listeners()
    preview_port = listeners[0].getsockname()[1]
    public_port = listeners[1].getsockname()[1]
    origins = ProjectOriginRepository(path, first_port=preview_port, last_port=public_port)
    origins.reserve('project')
    monkeypatch.setenv('ATOM_CONSOLE_ORIGIN', 'https://127.0.0.1')
    monkeypatch.setenv('ATOM_CONSOLE_PROOF_REQUIRED', 'true')
    monkeypatch.setenv('ATOM_IP_PREVIEW_ENABLED', 'true')
    monkeypatch.setenv('ATOM_IP_PREVIEW_ADDRESS', '127.0.0.1')
    monkeypatch.setenv('ATOM_IP_PREVIEW_FIRST_PORT', str(preview_port))
    monkeypatch.setenv('ATOM_IP_PREVIEW_LAST_PORT', str(public_port))
    monkeypatch.delenv('ATOM_CONTENT_HOST_SUFFIX')
    get_settings.cache_clear()
    proof = proof_for_new_session(token)
    app.state.execution = SimpleNamespace(store=store, repository=RevisionRepository(path))
    app.state.content_issuer = BoundedOperations(capacity=2)
    app.state.verifier_client = object()
    app.include_router(auth.router, prefix='/api')
    app.include_router(projects.router, prefix='/api')
    app.include_router(preview_access.router, prefix='/api')
    app.include_router(verifications.router, prefix='/api')
    _static(app, built_dist)
    outer = FastAPI()
    outer.mount('/atom', app)
    server, thread, port = _serve(outer)
    hosts = ProjectPortHosts('127.0.0.1', origins)
    key, cert = _tls_files(tmp_path)
    preview_server = preview_thread = None
    try:
        preview_server, preview_thread = _start(
            PreviewService(PreviewAccessRepository(path), store, hosts),
            listeners[0], key, cert)
        with sync_playwright() as playwright:
            browser_type = getattr(playwright, browser_name)
            browser = browser_type.launch(
                args=['--no-proxy-server'] if browser_name == 'chromium' else [])
            context = browser.new_context(ignore_https_errors=True, service_workers='block')
            context.add_cookies([{'name':'__Host-atom_console', 'value':token,
                'url':'https://127.0.0.1', 'secure':True, 'httpOnly':True, 'sameSite':'Lax'}])
            auth_requests = []
            def bridge(route):
                request = route.request
                if request.url == 'https://127.0.0.1/atom/_seed':
                    route.fulfill(status=200, content_type='text/html', body='<!doctype html>')
                    return
                if '/events?' in request.url:
                    route.abort('blockedbyclient')
                    return
                if request.url.endswith('/api/auth/me'):
                    auth_requests.append({name:bool(request.all_headers().get(name))
                        for name in ('cookie', 'x-atom-console-proof')})
                response = route.fetch(url=f'http://127.0.0.1:{port}' +
                    request.url[len('https://127.0.0.1'):], headers=request.all_headers() | {
                        'host':'127.0.0.1', 'x-forwarded-proto':'https',
                        'accept-encoding':'identity'}, timeout=10000)
                route.fulfill(status=response.status, headers={
                    name:value for name,value in response.headers.items() if name.lower()
                    not in ('content-encoding','content-length','transfer-encoding')},
                    body=response.body())
            context.route('https://127.0.0.1/atom/**', bridge)
            page = context.new_page()
            responses = []
            page.on('response', lambda response: responses.append((response.status, response.url.split('?')[0])))
            page.goto('https://127.0.0.1/atom/_seed', wait_until='domcontentloaded')
            page.evaluate("(value) => localStorage.setItem('atom.console.proof.v1', value)", proof)
            assert page.evaluate("localStorage.getItem('atom.console.proof.v1')") == proof
            page.goto('https://127.0.0.1/atom/app/p/project', wait_until='domcontentloaded')
            try:
                page.get_by_role('button', name='打开当前版本').wait_for(timeout=5000)
            except Exception as error:
                has_proof = page.evaluate('Boolean(localStorage.getItem("atom.console.proof.v1"))')
                has_cookie = any(item['name'] == '__Host-atom_console' for item in context.cookies())
                raise AssertionError(f'workspace={page.url} responses={responses[-15:]} '
                    f'proof={has_proof} cookie={has_cookie} '
                    f'auth_requests={auth_requests} '
                    f'origin={page.evaluate("location.origin")} '
                    f'body={page.locator("body").inner_text()[:800]}') from error
            assert page.locator('iframe').count() == 0
            exchange_responses = []
            exchange_requests = []
            context.on('request', lambda request: exchange_requests.append({
                name:request.all_headers().get(name)
                for name in ('origin', 'content-type', 'content-length', 'transfer-encoding')})
                if request.url.endswith('/_atom/exchange') else None)
            context.on('response', lambda response: exchange_responses.append(response.status)
                       if response.url.endswith('/_atom/exchange') else None)
            with context.expect_page() as opened:
                page.get_by_role('button', name='打开当前版本').click()
            child = opened.value
            try:
                child.wait_for_url(hosts.origin(preview_port) + '/', timeout=10000)
            except Exception as error:
                raise AssertionError(f'browser={browser_name} url={child.url} '
                    f'opening={child.locator("body").inner_text()[:200]} '
                    f'exchange={exchange_responses} request={exchange_requests}') from error
            assert child.locator('body').inner_text() == 'heat'
            assert child.evaluate('window.opener') is None
            assert child.evaluate('localStorage.getItem("atom.console.proof.v1")') is None
            child.evaluate("document.cookie='__Host-atom_console=forged; Secure; Path=/'")
            console_cookies = [item for item in context.cookies(['https://127.0.0.1'])
                               if item['name'] == '__Host-atom_console']
            assert len(console_cookies) == 1
            assert console_cookies[0]['value'] == token
            assert console_cookies[0]['httpOnly'] is True
            child_console_requests = []
            child.on('request', lambda request: child_console_requests.append(request.url)
                     if request.url.endswith('/api/auth/me') else None)
            result = child.evaluate("""async () => {
                try {
                    const response = await fetch('https://127.0.0.1/atom/api/auth/me',
                        {credentials: 'include'});
                    return response.status;
                } catch (_) {
                    return 'blocked';
                }
            }""")
            assert result == 'blocked'
            assert child_console_requests == []
            child.close()
            context.close()
            browser.close()
    finally:
        if preview_server is not None:
            preview_server.should_exit = True
            preview_thread.join(timeout=15)
        server.should_exit = True
        thread.join(timeout=15)
        for listener in listeners:
            listener.close()
        engine.dispose()
        get_settings.cache_clear()


@pytest.mark.parametrize('browser_name', ('chromium', 'firefox', 'webkit'))
def test_real_tls_console_cookie_survives_public_port_and_logout(
        http_history, tmp_path, monkeypatch, built_dist, browser_name):
    path, store, intent, _source, _displaced = http_history
    for version in range(14, 19):
        migrate(path, tmp_path / f'before-console-v{version}.db', target_version=version)
    app, _token, engine = _configured_api(path, store, intent, tmp_path, monkeypatch)
    listeners = _adjacent_listeners()
    preview_port, public_port = [sock.getsockname()[1] for sock in listeners]
    console_listener = socket.socket()
    console_listener.bind(('127.0.0.1', 443))
    console_listener.listen(32)
    origins = ProjectOriginRepository(path, first_port=preview_port, last_port=public_port)
    origins.reserve('project')
    console_origin = 'https://127.0.0.1'
    monkeypatch.setenv('ATOM_CONSOLE_ORIGIN', console_origin)
    monkeypatch.setenv('ATOM_CONSOLE_PROOF_REQUIRED', 'true')
    monkeypatch.delenv('ATOM_CONTENT_HOST_SUFFIX')
    get_settings.cache_clear()
    app.include_router(auth.router, prefix='/api')
    app.include_router(projects.router, prefix='/api')
    _static(app, built_dist)
    outer = FastAPI()
    outer.mount('/atom', app)
    repository = ContentRepository(path)
    public = ContentService(repository, store,
        ProjectPublicHosts('127.0.0.1', origins, repository))
    key, cert = _tls_files(tmp_path)
    services = []
    try:
        services.append(_start(public, listeners[1], key, cert))
        services.append(_start(outer, console_listener, key, cert))
        with sync_playwright() as playwright:
            browser_type = getattr(playwright, browser_name)
            browser = browser_type.launch(
                args=['--no-proxy-server'] if browser_name == 'chromium' else [])
            context = browser.new_context(ignore_https_errors=True, service_workers='block')
            try:
                console = context.new_page()
                account_email = f'isolated-{browser_name}@example.com'
                account_password = 'Browser-Isolation-2026!'
                console.goto(console_origin + '/atom/register')
                console.get_by_label('邮箱').fill(account_email)
                console.get_by_role('button', name='继续').click()
                try:
                    console.get_by_label('密码').wait_for(timeout=5000)
                except Exception as error:
                    raise AssertionError(f'registration lookup did not advance: '
                        f'url={console.url} body={console.locator("body").inner_text()[:500]}') from error
                console.get_by_label('密码').fill(account_password)
                console.get_by_role('button', name='创建账户').click()
                console.wait_for_url(console_origin + '/atom/app', timeout=10000)
                assert console.evaluate("Boolean(localStorage.getItem('atom.console.proof.v1'))")
                cookies = [item for item in context.cookies([console_origin])
                           if item['name'] == '__Host-atom_console']
                assert len(cookies) == 1 and cookies[0]['httpOnly'] is True
                token = cookies[0]['value']
                me = """async () => (await fetch('/atom/api/auth/me', {
                    credentials:'include', headers:{'x-atom-console-proof':
                    localStorage.getItem('atom.console.proof.v1')}})).status"""
                assert console.evaluate(me) == 200
                generated = context.new_page()
                generated.goto(f'https://127.0.0.1:{public_port}/')
                assert generated.locator('body').inner_text() == 'heat'
                assert generated.evaluate("localStorage.getItem('atom.console.proof.v1')") is None
                for method, route in (('GET', '/atom/api/auth/me'),
                                      ('POST', '/atom/api/auth/logout')):
                    assert generated.evaluate("""async ({url, method}) => {
                        try {
                            await fetch(url, {method, credentials:'include'});
                            return 'sent';
                        } catch (_) { return 'blocked'; }
                    }""", {'url':console_origin + route, 'method':method}) == 'blocked'
                generated.evaluate("document.cookie='__Host-atom_console=forged; Secure; Path=/'")
                cookies = [item for item in context.cookies([console_origin])
                           if item['name'] == '__Host-atom_console']
                assert len(cookies) == 1 and cookies[0]['value'] == token
                assert cookies[0]['httpOnly'] is True
                assert console.evaluate(me) == 200
                console.get_by_role('button', name='退出登录').click()
                console.wait_for_url(console_origin + '/atom/login', timeout=10000)
                assert console.evaluate("localStorage.getItem('atom.console.proof.v1')") is None
                assert console.evaluate(me) == 401
                console.goto(console_origin + '/atom/login')
                console.get_by_label('邮箱').fill(account_email)
                console.get_by_role('button', name='继续').click()
                console.get_by_label('密码').fill(account_password)
                console.get_by_role('button', name='登录', exact=True).click()
                console.wait_for_url(console_origin + '/atom/app', timeout=10000)
                assert console.evaluate(me) == 200
                renewed = [item for item in context.cookies([console_origin])
                           if item['name'] == '__Host-atom_console']
                assert len(renewed) == 1 and renewed[0]['value'] != token
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
        console_listener.close()
        engine.dispose()
        get_settings.cache_clear()
