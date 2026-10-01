"""Actual Chromium observations against a disposable loopback content origin."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread

import pytest
from playwright.sync_api import sync_playwright

from app.verification_contract import capture_contract
from app.verification_observer import ObservationError, observe_contract


@pytest.fixture
def sites():
    counters = {'external': 0, 'worker': 0}

    class External(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            counters['external'] += 1
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'escaped')

    external = ThreadingHTTPServer(('127.0.0.1', 0), External)
    outside = f'http://127.0.0.1:{external.server_port}'
    page = {'html': ''}

    class Content(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            if self.path == '/worker.js':
                counters['worker'] += 1
                body = b"self.addEventListener('install', () => self.skipWaiting());"
                content_type = 'application/javascript'
            else:
                body = page['html'].encode() if self.path == '/' else b''
                content_type = 'text/html'
            self.send_response(200 if body else 404)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    content = ThreadingHTTPServer(('127.0.0.1', 0), Content)
    threads = [Thread(target=server.serve_forever, daemon=True) for server in (external, content)]
    for thread in threads:
        thread.start()
    try:
        yield f'http://127.0.0.1:{content.server_port}/', outside, page, counters
    finally:
        for server in (content, external):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=2)


def _contract(checks):
    return capture_contract([{'key': 'page', 'title': 'Page', 'detail': '', 'checks': checks}])


def _run(contract, url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            return json.loads(observe_contract(browser, contract, url).canonical)['results']
        finally:
            browser.close()


def test_actual_dom_flow_and_fresh_context_per_check(sites):
    url, _outside, page, _counter = sites
    page['html'] = '''<!doctype html><input id="name"><button id="go">Go</button>
        <span id="ready" hidden>Ready</span><span id="state"></span>
        <script>
        document.querySelector('#state').textContent = localStorage.getItem('count') || '0';
        document.querySelector('#go').onclick = () => {
          localStorage.setItem('count','1'); document.querySelector('#ready').hidden=false;
        };
        </script>'''
    checks = [
        {'type': 'exists', 'selector': '#go'},
        {'type': 'flow', 'selector': '#go', 'setup': [{'action': 'fill', 'selector': '#name', 'value': 'Atom'}],
         'expect': '#ready'},
        {'type': 'text', 'selector': '#state', 'contains': '0'},
    ]
    result = _run(_contract(checks), url)
    assert [(item['checkIndex'], item['passed']) for item in result] == [(0, True), (1, True), (2, True)]
    assert all(item['note'] == 'observed' for item in result)


def test_unmet_and_invalid_selector_are_observed_failures(sites):
    url, _outside, page, _counter = sites
    page['html'] = '<div id="title">Actual content</div>'
    result = _run(_contract([
        {'type': 'text', 'selector': '#title', 'contains': 'Untrue'},
        {'type': 'exists', 'selector': '???'},
    ]), url)
    assert [item['passed'] for item in result] == [False, False]
    assert all(item['note'] == 'check_unmet' for item in result)


def test_cross_origin_request_is_blocked_and_cannot_pass(sites):
    url, outside, page, counters = sites
    page['html'] = f'''<button id="go">Go</button><span id="ready" hidden>Ready</span>
        <script>document.querySelector('#go').onclick=async()=>{{
          try {{ await fetch('{outside}/escape'); }} catch (_) {{}}
          document.querySelector('#ready').hidden=false;
        }};</script>'''
    result = _run(_contract([{'type': 'flow', 'selector': '#go', 'expect': '#ready'}]), url)
    assert result[0]['passed'] is False
    assert result[0]['note'] == 'content_policy_denied'
    assert counters['external'] == 0


def test_cross_origin_navigation_is_blocked_and_cannot_pass(sites):
    url, outside, page, counters = sites
    page['html'] = f'''<button id="go">Go</button><span id="ready">Ready</span>
        <script>document.querySelector('#go').onclick=()=>location.href='{outside}/escape';</script>'''
    result = _run(_contract([{'type': 'flow', 'selector': '#go', 'expect': '#ready'}]), url)
    assert result[0]['passed'] is False
    assert result[0]['note'] == 'content_policy_denied'
    assert counters['external'] == 0


def test_websocket_attempt_is_blocked_and_cannot_pass(sites):
    url, outside, page, counters = sites
    socket_url = outside.replace('http://', 'ws://') + '/socket'
    page['html'] = f'''<button id="go">Go</button><span id="ready" hidden>Ready</span>
        <script>document.querySelector('#go').onclick=()=>{{
          const socket=new WebSocket('{socket_url}');
          socket.onerror=()=>document.querySelector('#ready').hidden=false;
        }};</script>'''
    result = _run(_contract([{'type': 'flow', 'selector': '#go', 'expect': '#ready'}]), url)
    assert result[0]['passed'] is False
    assert result[0]['note'] == 'content_policy_denied'
    assert counters['external'] == 0


def test_service_worker_registration_is_blocked(sites):
    url, _outside, page, counters = sites
    page['html'] = '''<span id="status">pending</span><script>
        navigator.serviceWorker.register('/worker.js').catch(() => {});
        setTimeout(() => document.querySelector('#status').textContent='settled', 750);
        </script>'''
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            control = browser.new_context(service_workers='allow')
            control_page = control.new_page()
            control_page.goto(url)
            control_page.locator('#status').first.wait_for(state='visible')
            control_page.wait_for_timeout(1000)
            control.close()
        finally:
            browser.close()
    assert counters['worker'] > 0
    before = counters['worker']
    result = _run(_contract([{'type': 'text', 'selector': '#status', 'contains': 'settled'}]), url)
    assert result[0]['passed'] is True
    assert counters['worker'] == before


def test_overall_budget_denies_a_late_report(sites):
    url, _outside, page, _counters = sites
    page['html'] = '<div id="ready">Ready</div>'
    contract = _contract([{'type': 'flow', 'selector': '#missing', 'expect': '#ready'}])
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            with pytest.raises(ObservationError, match='verification_deadline'):
                observe_contract(browser, contract, url, budget_seconds=1)
        finally:
            browser.close()


def test_invalid_entry_is_rejected_before_browser_activity(sites):
    url, _outside, _page, _counter = sites
    contract = _contract([{'type': 'exists', 'selector': 'body'}])
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for entry in (url + 'other', 'http://example.com/', url + '?revision=other'):
                with pytest.raises(ObservationError):
                    observe_contract(browser, contract, entry)
        finally:
            browser.close()
