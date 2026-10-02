"""Actual built UI and local FastAPI/SQLite checks; no model/provider claim."""
from datetime import datetime, timedelta, timezone
import json

from fastapi import FastAPI
from playwright.sync_api import expect, sync_playwright
import pytest

from app import storage
from app.db import session_scope
from app.models import Project, Requirement, Run
from app.routers import auth, preview, projects
from test_release_workbench_browser import built_dist, _serve, _static


@pytest.mark.parametrize("viewport", [
    {"width": 1280, "height": 800}, {"width": 390, "height": 844},
])
def test_real_functional_checks_save_reload_and_service_failure(signed_in, built_dist, tmp_path, viewport):
    pid = signed_in.post('/api/projects', json={'prompt': 'Check a real interactive page'}).json()['project']['id']
    with session_scope() as session:
        session.get(Project, pid).status = 'ready'
        session.add(Requirement(project_id=pid, key='button', title='按钮操作',
            detail='点击按钮后显示完成', checks_json=json.dumps([
                {'type': 'flow', 'selector': '#action', 'expect': '#done'}])))
        session.add(Run(project_id=pid, role='engineer', model='test-fixture',
            phase='build', status='succeeded', started_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
    workspace = storage.workspace_dir(pid)
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / 'index.html').write_text(
        '<!doctype html><html><body><button id="action" '
        'onclick="document.getElementById(\'result\').innerHTML=\'<p id=done>完成</p>\'">'
        '执行</button><div id="result"></div></body></html>', encoding='utf-8')
    app = FastAPI()
    app.include_router(auth.router, prefix='/api')
    app.include_router(projects.router, prefix='/api')
    app.include_router(preview.router)
    _static(app, built_dist)
    outer = FastAPI()
    outer.mount('/atom', app)
    server, thread, port = _serve(outer)
    origin = f'http://127.0.0.1:{port}'
    errors = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(viewport=viewport)
            context.add_cookies([{'name': name, 'value': value, 'url': origin}
                for name, value in signed_in.cookies.items()])
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'{origin}/atom/app/p/{pid}', wait_until='domcontentloaded')
            page.get_by_role('tab', name='契约', exact=True).click()
            with page.expect_response(lambda response: response.url.endswith('/acceptance')) as saved:
                page.get_by_role('button', name='检查功能', exact=True).click()
            assert saved.value.status == 200
            expect(page.get_by_text('功能检查通过', exact=True)).to_be_visible()
            page.reload(wait_until='domcontentloaded')
            page.get_by_role('tab', name='契约', exact=True).click()
            expect(page.get_by_text('功能检查通过', exact=True)).to_be_visible()
            # Deliberate transport fault: never classify service failure as a failed assertion.
            page.route('**/acceptance', lambda route: route.fulfill(status=500, body='server unavailable'))
            page.get_by_role('button', name='检查功能', exact=True).click()
            expect(page.get_by_text('检查未完成', exact=True)).to_be_visible()
            expect(page.get_by_text('检查结果暂时无法保存，请稍后重试。这不代表网页功能不合格。')).to_be_visible()
            expect(page.get_by_text('上次已保存的检查结果', exact=True)).to_be_visible()
            assert page.get_by_text('验收失败', exact=True).count() == 0
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            page.screenshot(path=str(tmp_path / f'checks-{viewport["width"]}.png'), full_page=True)
            assert not errors
            context.close()
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        assert not thread.is_alive()
