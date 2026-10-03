"""Opt-in production Chromium check with a short-lived, revoked owner session.

Run from an operator workstation with Playwright installed. Credentials remain
in process memory and are never printed or written to disk. The browser gets a
separate context, so the owner's normal Chrome session is unaffected.
"""

import json
import os
import subprocess

from playwright.sync_api import sync_playwright


REMOTE_SETUP = '''
import json, os
from sqlalchemy import select
from app.access_repository import AccessRepository
from app.config import get_settings
from app.console_auth import proof_for_new_session
from app.db import SessionLocal
from app.durable_credentials import DurableConsoleCredentials
from app.models import Project
from app.project_origins import ProjectOriginRepository

settings = get_settings()
if (settings.environment != 'production' or settings.session_mode != 'durable'
        or not settings.console_proof_required or not settings.ip_public_enabled
        or settings.console_origin != os.environ['ATOM_LIVE_EXPECTED_CONSOLE_ORIGIN']):
    raise RuntimeError('production_boundary_required')
first = os.environ['ATOM_LIVE_FIRST_PROJECT_ID']
second = os.environ['ATOM_LIVE_SECOND_PROJECT_ID']
origins = ProjectOriginRepository(settings.db_path,
    first_port=settings.ip_preview_first_port, last_port=settings.ip_preview_last_port)
with SessionLocal() as db:
    projects = [db.get(Project, item) for item in (first, second)]
    if (first == second or any(item is None for item in projects)
            or projects[0].user_id != projects[1].user_id):
        raise RuntimeError('distinct_owned_projects_required')
    owner_id = projects[0].user_id
pairs = [origins.for_project(item) for item in (first, second)]
if any(pair is None for pair in pairs):
    raise RuntimeError('project_origin_missing')
repository = AccessRepository(settings.db_path)
session = repository.create_console_session(user_id=owner_id, lifetime_seconds=180)
try:
    codec = DurableConsoleCredentials(repository, key=settings.secret,
        issuer='atom-console', audience='atom-console')
    token = codec.sign(user_id=owner_id, session_id=session.id)
    proof = proof_for_new_session(token)
except Exception:
    repository.revoke_console_session(user_id=owner_id, session_id=session.id)
    raise
print(json.dumps({'owner': owner_id, 'session': session.id, 'token': token,
    'proof': proof, 'console': settings.console_origin,
    'public': [f'https://{settings.ip_preview_address}:{pair.public_port}/'
               for pair in pairs]}))
'''


def _remote(source: str, *, first: str, second: str) -> str:
    command = ['ssh', '-o', 'BatchMode=yes', os.environ['ATOM_LIVE_SSH_TARGET'],
        'sudo', 'docker', 'exec', '-i',
        '-e', f'ATOM_LIVE_FIRST_PROJECT_ID={first}',
        '-e', f'ATOM_LIVE_SECOND_PROJECT_ID={second}',
        '-e', 'ATOM_LIVE_EXPECTED_CONSOLE_ORIGIN='
            + os.environ['ATOM_LIVE_EXPECTED_CONSOLE_ORIGIN'],
        os.environ['ATOM_LIVE_API_CONTAINER'],
        os.environ.get('ATOM_LIVE_API_PYTHON', '/app/backend/.venv/bin/python'), '-']
    result = subprocess.run(command, input=source, text=True, capture_output=True,
                            timeout=35, check=False)
    if result.returncode:
        raise RuntimeError('remote_probe_failed')
    return result.stdout


def main() -> None:
    if os.environ.get('ATOM_LIVE_BROWSER_PORT_PROBE') != '1':
        raise RuntimeError('explicit_live_browser_opt_in_required')
    first = os.environ['ATOM_LIVE_FIRST_PROJECT_ID']
    second = os.environ['ATOM_LIVE_SECOND_PROJECT_ID']
    session = json.loads(_remote(REMOTE_SETUP, first=first, second=second))
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(args=['--no-proxy-server'])
            context = browser.new_context(service_workers='block')
            try:
                console = context.new_page()
                # Use an inert JSON document so the SPA cannot race the synthetic
                # session setup by clearing proof after an initial unauthenticated load.
                console.goto(session['console'] + '/atom/api/auth/me',
                             wait_until='domcontentloaded')
                console.evaluate("value => localStorage.setItem('atom.console.proof.v1', value)",
                                 session['proof'])
                context.add_cookies([{'name': '__Host-atom_console',
                    'value': session['token'], 'url': session['console'],
                    'secure': True, 'httpOnly': True, 'sameSite': 'Lax'}])
                me = """async () => (await fetch('/atom/api/auth/me', {
                    credentials:'include', headers:{'x-atom-console-proof':
                    localStorage.getItem('atom.console.proof.v1')}})).status"""
                assert console.evaluate(me) == 200
                original = [cookie for cookie in context.cookies([session['console']])
                            if cookie['name'] == '__Host-atom_console']
                assert len(original) == 1 and original[0]['httpOnly']
                for public_url in session['public']:
                    page = context.new_page()
                    response = page.goto(public_url, wait_until='domcontentloaded')
                    assert response is not None and response.status == 200
                    assert page.evaluate("localStorage.getItem('atom.console.proof.v1')") is None
                    assert page.evaluate('window.opener === null')
                    prior_status = console.evaluate(me)
                    assert prior_status == 200, f'console_lost_before_attack={prior_status}'
                    observed = []
                    page.on('response', lambda item: observed.append(item.status)
                            if '/atom/api/auth/logout' in item.url else None)
                    attempted = page.evaluate("""async url => {
                        try { await fetch(url, {method:'POST', credentials:'include'});
                              return 'sent'; }
                        catch (_) { return 'blocked'; }
                    }""", session['console'] + '/atom/api/auth/logout')
                    assert attempted == 'blocked'
                    after_fetch_status = console.evaluate(me)
                    assert after_fetch_status == 200, (
                        f'console_lost_after_cross_port_fetch={after_fetch_status} '
                        f'response_statuses={observed}')
                    page.evaluate("document.cookie='__Host-atom_console=forged; Secure; Path=/'")
                    post_plant_status = console.evaluate(me)
                    if post_plant_status != 200:
                        current = [cookie for cookie in context.cookies([session['console']])
                                   if cookie['name'] == '__Host-atom_console']
                        raise AssertionError('cookie_plant_boundary_failed: '
                            f'status={post_plant_status} count={len(current)} '
                            f'original_preserved={current == original} '
                            f'http_only={[item["httpOnly"] for item in current]} '
                            f'proof_preserved={console.evaluate("localStorage.getItem(\"atom.console.proof.v1\")") == session["proof"]}')
                    page.close()
                remaining = [cookie for cookie in context.cookies([session['console']])
                             if cookie['name'] == '__Host-atom_console']
                assert remaining == original
                logout = console.evaluate("""async () => (await fetch('/atom/api/auth/logout', {
                    method:'POST', credentials:'include', headers:{'x-atom-console-proof':
                    localStorage.getItem('atom.console.proof.v1')}})).status""")
                assert logout == 200
                assert console.evaluate(me) == 401
                print('live_browser_port_boundary_verified: two_public_origins=200 '
                      'console_authenticated=200 cross_port_logout=blocked '
                      'cookie_unchanged=true logout=200 revoked_me=401')
            finally:
                context.close()
                browser.close()
    finally:
        cleanup = '''
from app.access_repository import AccessRepository
from app.config import get_settings
AccessRepository(get_settings().db_path).revoke_console_session(
    user_id=%r, session_id=%r)
''' % (session['owner'], session['session'])
        _remote(cleanup, first=first, second=second)


if __name__ == '__main__':
    main()
