"""Opt-in read-only live browser latency probe; ephemeral session is revoked.

Uses the existing production-boundary harness. Emits timings/counts only, never
cookies, proof, project content or full browser traces. All targets are supplied
by the operator environment; no production address or credential is embedded.
"""
import importlib.util
import json
import os
from pathlib import Path
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, expect


def main():
    if os.environ.get('ATOM_LIVE_WORKSPACE_PROBE') != '1':
        raise RuntimeError('explicit_live_workspace_opt_in_required')
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('boundary', root /
        'backend/tests/integration/live_browser_port_boundary.py')
    boundary = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(boundary)
    projects = os.environ['ATOM_LIVE_PROJECT_IDS'].split(',')
    first, second = projects[:2]
    setup = boundary.REMOTE_SETUP.replace('lifetime_seconds=180', 'lifetime_seconds=600')
    session = json.loads(boundary._remote(setup, first=first, second=second))
    results = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=['--no-proxy-server'])
            context = browser.new_context(viewport={'width': 1440, 'height': 900})
            page = context.new_page()
            page.goto(session['console'] + '/atom/api/auth/me', wait_until='domcontentloaded')
            page.evaluate("value => localStorage.setItem('atom.console.proof.v1',value)", session['proof'])
            context.add_cookies([{'name': '__Host-atom_console', 'value': session['token'],
                'url': session['console'], 'secure': True, 'httpOnly': True, 'sameSite': 'Lax'}])
            errors, requests, responses = [], [], []
            page.on('pageerror', lambda _: errors.append('page_error'))
            page.on('request', lambda req: requests.append((urlparse(req.url).path, time.perf_counter())))
            page.on('response', lambda res: responses.append((urlparse(res.url).path, res.status)))
            page.goto(session['console'] + '/atom/app', wait_until='domcontentloaded')
            for index in range(int(os.environ.get('ATOM_LIVE_PROBE_COUNT', '12'))):
                project = projects[index % len(projects)]
                path = '/atom/api/projects/' + project
                link = page.locator('a[href="/atom/app/p/' + project + '"]').first
                link.wait_for(state='visible', timeout=30000)
                title = link.locator('span.truncate').inner_text()
                requests.clear()
                responses.clear()
                start = time.perf_counter()
                link.click()
                status = 'visible'
                try:
                    expect(page.locator('header h1')).to_have_text(title, timeout=45000)
                except Exception:
                    status = 'timeout_or_error'
                elapsed = round((time.perf_counter() - start) * 1000)
                # Let the replay settle; count all requests caused by this opening.
                page.wait_for_timeout(2000)
                result = {'sample': index + 1, 'project': project, 'visible_ms': elapsed,
                    'result': status, 'detail_requests': sum(item[0] == path for item in requests),
                    'detail_statuses': [code for target, code in responses if target == path]}
                results.append(result)
                print(json.dumps(result), flush=True)
            evidence = os.environ.get('ATOM_LIVE_SCREENSHOT')
            if evidence:
                page.screenshot(path=evidence)
            print(json.dumps({'page_errors': len(errors), 'samples': len(results)}), flush=True)
            context.close()
            browser.close()
    finally:
        cleanup = '''
from app.access_repository import AccessRepository
from app.config import get_settings
AccessRepository(get_settings().db_path).revoke_console_session(user_id=%r,session_id=%r)
''' % (session['owner'], session['session'])
        boundary._remote(cleanup, first=first, second=second)


if __name__ == '__main__':
    main()
