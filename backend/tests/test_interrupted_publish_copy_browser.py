"""A saved, unfinished revision has truthful publish guidance in the built UI."""

import sqlite3
import time
from types import SimpleNamespace

from fastapi import FastAPI
from playwright.sync_api import sync_playwright
import pytest

from app.config import get_settings
from app.migrations import migrate
from app.revision_view import committed_catalog
from app.revisions import RevisionRepository
from app.routers import auth, projects, verifications
from test_adoption_repository import prepared, snapshot  # imported fixtures feed http_history
from test_adoption_verification_repository import adopted  # imported fixture feeds http_history
from test_release_workbench_browser import ORIGIN, _serve, _static, built_dist
from test_revision_migrations import legacy  # imported fixture feeds prepared
from test_rollback_v14_api import _configured_api, http_history


@pytest.mark.parametrize('viewport', [
    pytest.param({'width': 1280, 'height': 800}, id='desktop'),
    pytest.param({'width': 390, 'height': 844}, id='mobile'),
])
def test_saved_unfinished_version_distinguishes_ready_gate_from_optional_check(
        http_history, tmp_path, monkeypatch, built_dist, viewport):
    path, store, intent, _source, _displaced = http_history
    for version in (14, 15, 16):
        migrate(path, tmp_path / f'before-interrupted-v{version}.db', target_version=version)

    _, artifact = snapshot(b'<html>heat</html>')
    revisions = RevisionRepository(path)
    workspace = revisions.find_workspace('user', 'project', None)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE projects SET active_run_id='run' WHERE id='project'")
    revisions.reserve('user', workspace, 'run', 'interrupted-build', 'interrupted-grant',
                      int(time.time()) + 120)
    revisions.bind('user', 'interrupted-build', 'interrupted-worker')
    receipt = revisions.register('user', 'interrupted-build', 'interrupted-worker',
                                 'interrupted-grant', artifact)
    revisions.observe_termination('user', 'interrupted-build', confirmed=True,
                                   outcome='cancelled')
    with sqlite3.connect(path) as db:
        db.execute("UPDATE projects SET active_run_id=NULL,status='cancelled' WHERE id='project'")
    listing = committed_catalog(revisions, store, owner='user', project_id='project')
    assert listing['incompleteSavedRevisionId'] == receipt.revision_id

    app, token, engine = _configured_api(path, store, intent, tmp_path, monkeypatch)
    monkeypatch.setenv('ATOM_PUBLICATION_VERIFICATION', 'advisory')
    for name in ('ATOM_VERIFIER_ORIGIN', 'ATOM_VERIFIER_CONTROL_TOKEN',
                 'ATOM_VERIFIER_POLICY_DIGEST', 'ATOM_VERIFIER_RUNNER_VERSION'):
        monkeypatch.delenv(name)
    get_settings.cache_clear()
    app.state.execution = SimpleNamespace(store=store, repository=revisions)
    app.state.verifier_client = None
    app.include_router(auth.router, prefix='/api')
    app.include_router(projects.router, prefix='/api')
    app.include_router(verifications.router, prefix='/api')
    _static(app, built_dist)
    outer = FastAPI()
    outer.mount('/atom', app)
    server, thread, port = _serve(outer)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(args=['--no-proxy-server'])
            context = browser.new_context(viewport=viewport,
                service_workers='block', ignore_https_errors=True)
            context.add_cookies([{'name': '__Host-atom_console', 'value': token,
                'url': ORIGIN, 'secure': True, 'httpOnly': True, 'sameSite': 'Lax'}])

            def bridge(route):
                request = route.request
                if '/events?' in request.url:
                    route.abort('blockedbyclient')
                    return
                headers = request.headers | {'host': 'console.example.org',
                    'x-forwarded-proto': 'https', 'accept-encoding': 'identity'}
                response = route.fetch(url=f'http://127.0.0.1:{port}'
                    + request.url[len(ORIGIN):], headers=headers, timeout=10000)
                route.fulfill(status=response.status,
                    headers={key: value for key, value in response.headers.items()
                             if key.lower() not in ('content-encoding', 'content-length',
                                                    'transfer-encoding')},
                    body=response.body())

            context.route(ORIGIN + '/atom/**', bridge)
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(ORIGIN + '/atom/app/p/project', wait_until='domcontentloaded')
            banner = page.get_by_role('status').filter(has_text='已保存未完成版本')
            banner.wait_for()
            assert '完成生成后才能发布这个版本' in banner.inner_text()
            assert '功能检查可按需运行' in banner.inner_text()
            assert '验收' not in banner.inner_text()
            page.get_by_role('tab', name='发布', exact=True).click()
            panel = page.get_by_label('发布与历史', exact=True)
            panel.get_by_text('功能检查可按需运行，不影响发布。', exact=False).wait_for()
            assert panel.get_by_role('button', name='发布更新', exact=True).is_disabled()
            panel.get_by_text('请等待网页生成完成后发布。', exact=True).wait_for()
            assert panel.get_by_label('发布历史').get_by_role('listitem').count() == 2
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert not errors, errors
            context.close()
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        engine.dispose()
        get_settings.cache_clear()
