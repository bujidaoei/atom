"""Real built SPA + HTTP/SSE/SQLite; injected latency/errors are test faults."""
import asyncio
from collections import Counter
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from playwright.sync_api import sync_playwright, expect
from sqlalchemy import select

from app.db import session_scope
from app.events import EventBus
from app.models import Project, User
from app.routers import auth, projects
from app.security import issue_session
from test_release_workbench_browser import _serve, _static, built_dist


def test_replay_switch_failure_and_reconnect(signed_in, monkeypatch, built_dist):
    bus = EventBus()
    monkeypatch.setattr(projects, 'bus', bus)
    identifiers = []
    for title in ('Latency Alpha', 'Latency Beta'):
        result = signed_in.post('/api/projects', json={'prompt': title})
        assert result.status_code == 201
        identifiers.append(result.json()['project']['id'])
    with session_scope() as db:
        owner = db.scalar(select(User))
        token = issue_session(owner.id)
        for identifier, title in zip(identifiers, ('Latency Alpha', 'Latency Beta')):
            project = db.get(Project, identifier)
            project.status, project.title = 'ready', title
    for identifier in identifiers:
        for _ in range(30):
            bus._persist(identifier, 'project.updated', {'status': 'ready'}, None, None)

    app = FastAPI()
    calls = Counter()
    faults = {'delay': .3, 'fail': False}

    @app.middleware('http')
    async def detail_fault(request, call_next):
        if request.url.path in ['/atom/api/projects/' + item for item in identifiers]:
            calls[request.url.path.rsplit('/', 1)[1]] += 1
            await asyncio.sleep(faults['delay'])
            if faults['fail']:
                return JSONResponse({'detail': 'Injected read failure'}, status_code=503)
        return await call_next(request)

    inner = FastAPI()
    inner.include_router(auth.router, prefix='/api')
    inner.include_router(projects.router, prefix='/api')

    @inner.post('/__test/disconnect')
    async def disconnect():
        await bus.publish(identifiers[0], 'stream.resync', {})
        return {'ok': True}

    @inner.post('/__test/update')
    async def update():
        with session_scope() as db:
            db.get(Project, identifiers[0]).title = 'Latency Alpha Updated'
        await bus.publish(identifiers[0], 'project.updated', {'status': 'ready'})
        return {'ok': True}

    _static(inner, built_dist)
    app.mount('/atom', inner)
    server, thread, port = _serve(app)
    origin = f'http://127.0.0.1:{port}'
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            context = browser.new_context()
            context.add_cookies([{'name': 'atom_session', 'value': token, 'url': origin}])
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(origin + '/atom/app/p/' + identifiers[0])
            expect(page.locator('header h1')).to_have_text('Latency Alpha')
            page.wait_for_timeout(500)
            assert calls[identifiers[0]] == 1, 'historic updates must not amplify detail reads'
            page.locator('a[href="/atom/app/p/' + identifiers[1] + '"]').click()
            expect(page.locator('header h1')).to_have_text('Latency Beta')
            # Switch away while Alpha's actual HTTP response remains pending.
            faults['delay'] = 1.5
            page.locator('a[href="/atom/app/p/' + identifiers[0] + '"]').click()
            page.wait_for_timeout(100)
            page.locator('a[href="/atom/app/p/' + identifiers[1] + '"]').click()
            expect(page.locator('header h1')).to_have_text('Latency Beta')
            page.wait_for_timeout(1700)
            expect(page.locator('header h1')).to_have_text('Latency Beta')
            faults.update(delay=.05, fail=True)
            page.locator('a[href="/atom/app/p/' + identifiers[0] + '"]').click()
            expect(page.get_by_text('Injected read failure', exact=True)).to_be_visible()
            faults['fail'] = False
            page.get_by_role('button', name='重试', exact=True).click()
            expect(page.locator('header h1')).to_have_text('Latency Alpha')
            assert page.request.post(origin + '/atom/__test/update').status == 200
            expect(page.locator('header h1')).to_have_text('Latency Alpha Updated')
            before = calls[identifiers[0]]
            assert page.request.post(origin + '/atom/__test/disconnect').status == 200
            page.wait_for_timeout(2300)
            expect(page.locator('header h1')).to_have_text('Latency Alpha Updated')
            assert calls[identifiers[0]] > before, 'reconnect must reconcile persistent state'
            assert calls[identifiers[0]] <= before + 2
            assert errors == []
            output = Path(__file__).resolve().parents[2] / '.logs/workspace-browser.png'
            output.parent.mkdir(exist_ok=True)
            page.screenshot(path=str(output))
            context.close()
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        assert not thread.is_alive()
