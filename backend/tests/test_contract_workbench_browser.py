"""Real HTTP/SQLite/UI composition; scripted model is a separate fault-test boundary."""
from pathlib import Path

from fastapi import FastAPI
from playwright.sync_api import sync_playwright, expect
import pytest

from app.main import app
from app.routers import projects
from app.services.orchestrator import Orchestrator
from test_contract_refinement import PlanningRuntime, seed
from test_release_workbench_browser import built_dist, _serve, _static


@pytest.mark.parametrize('viewport', [{'width': 1280, 'height': 900}, {'width': 390, 'height': 844}])
def test_iterate_preview_restore_reload(signed_in, built_dist, monkeypatch, viewport):
    pid, _, initial = seed(signed_in)
    runtime = PlanningRuntime()
    monkeypatch.setattr(projects, 'orchestrator', Orchestrator(runtime))
    inner = FastAPI()
    inner.router.routes.extend(app.router.routes)
    inner.exception_handlers.update(app.exception_handlers)
    _static(inner, built_dist)
    outer = FastAPI()
    outer.mount('/atom', inner)
    server, thread, port = _serve(outer)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(viewport=viewport)
            origin = f'http://127.0.0.1:{port}'
            context.add_cookies([{'name': 'atom_session', 'value': signed_in.cookies.get('atom_session'), 'url': origin}])
            page = context.new_page()
            failures = []
            page.on('pageerror', lambda error: failures.append(str(error)))
            page.goto(f'{origin}/atom/app/p/{pid}')
            page.get_by_role('tab', name='契约', exact=True).click()
            note = page.get_by_label('顺手微调（可选）')
            for message in ('增加落子音效', '再增加静音按钮'):
                note.fill(message)
                expect(page.get_by_role('button', name='开始构建', exact=True)).to_be_disabled()
                page.get_by_role('button', name='继续微调', exact=True).click()
                expect(note).to_have_value('', timeout=15000)
                expect(page.get_by_role('button', name='开始构建', exact=True)).to_be_enabled()
            history = page.get_by_role('region', name='契约历史', exact=True)
            expect(history.get_by_role('listitem')).to_have_count(3)
            oldest = history.get_by_role('listitem').last
            oldest.get_by_role('button', name='预览', exact=True).click()
            preview = page.get_by_role('region', name='契约版本 1 预览', exact=True)
            expect(preview.get_by_role('heading', name='棋盘', exact=True)).to_be_visible()
            page.get_by_role('button', name='关闭预览', exact=True).click()
            oldest.get_by_role('button', name='恢复此版本', exact=True).click()
            page.get_by_role('button', name='确认恢复', exact=True).click()
            expect(history.get_by_role('listitem')).to_have_count(4)
            page.reload()
            page.get_by_role('tab', name='契约', exact=True).click()
            expect(page.get_by_role('heading', name='棋盘', exact=True)).to_be_visible()
            expect(page.get_by_role('region', name='契约历史', exact=True).get_by_role('listitem')).to_have_count(4)
            assert not failures, failures
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            output = Path(__file__).resolve().parents[2] / '.logs' / 'contract-browser'
            output.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(output / f'{viewport["width"]}.png'), full_page=True)
            with page.expect_response(lambda response: response.url.endswith(f'/api/projects/{pid}/approve')) as approval:
                page.get_by_role('button', name='开始构建', exact=True).click()
            assert approval.value.ok, approval.value.text()
            context.close(); browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
