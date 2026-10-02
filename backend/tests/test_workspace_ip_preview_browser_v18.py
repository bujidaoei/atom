"""Built workspace opens the exact saved revision on an isolated IP TLS port."""
import json
from types import SimpleNamespace

from fastapi import FastAPI
from playwright.sync_api import sync_playwright

from app.bounded_operations import BoundedOperations
from app.config import get_settings
from app.console_auth import proof_for_new_session
from app.migrations import migrate
from app.preview_access import PreviewAccessRepository
from app.preview_service import PreviewService
from app.project_origins import ProjectOriginRepository
from app.project_port_hosts import ProjectPortHosts
from app.revisions import RevisionRepository
from app.routers import auth, preview_access, projects, verifications
from test_ip_preview_browser_v18 import _adjacent_listeners, _start, _tls_files
from test_release_workbench_browser import _serve, _static, built_dist
from test_rollback_v14_api import _configured_api, http_history
from test_adoption_verification_repository import adopted
from test_adoption_repository import prepared
from test_revision_migrations import legacy


def test_workspace_opens_isolated_saved_preview(
        http_history, tmp_path, monkeypatch, built_dist):
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
            browser = playwright.chromium.launch(args=['--no-proxy-server'])
            context = browser.new_context(ignore_https_errors=True, service_workers='block')
            context.add_cookies([{'name':'__Host-atom_console', 'value':token,
                'url':'https://127.0.0.1', 'secure':True, 'httpOnly':True, 'sameSite':'Lax'}])
            context.add_init_script('''if (location.origin === 'https://127.0.0.1')
                localStorage.setItem('atom.console.proof.v1', ''' + json.dumps(proof) + ');')
            def bridge(route):
                request = route.request
                if '/events?' in request.url:
                    route.abort('blockedbyclient')
                    return
                response = route.fetch(url=f'http://127.0.0.1:{port}' +
                    request.url[len('https://127.0.0.1'):], headers=request.headers | {
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
            page.goto('https://127.0.0.1/atom/app/p/project', wait_until='domcontentloaded')
            try:
                page.get_by_role('button', name='打开当前版本').wait_for(timeout=5000)
            except Exception as error:
                has_proof = page.evaluate('Boolean(localStorage.getItem("atom.console.proof.v1"))')
                has_cookie = any(item['name'] == '__Host-atom_console' for item in context.cookies())
                raise AssertionError(f'workspace={page.url} responses={responses[-15:]} '
                    f'proof={has_proof} cookie={has_cookie} '
                    f'body={page.locator("body").inner_text()[:800]}') from error
            assert page.locator('iframe').count() == 0
            with context.expect_page() as opened:
                page.get_by_role('button', name='打开当前版本').click()
            child = opened.value
            child.wait_for_url(hosts.origin(preview_port) + '/', timeout=10000)
            assert child.locator('body').inner_text() == 'heat'
            assert child.evaluate('window.opener') is None
            assert child.evaluate('localStorage.getItem("atom.console.proof.v1")') is None
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
