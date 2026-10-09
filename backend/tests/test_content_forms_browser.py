"""Real browser form semantics and transport isolation under delivery policy."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from playwright.sync_api import sync_playwright
import pytest

from app.content_service import HEADERS


@contextmanager
def form_origin():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            requests.append(('GET', self.path))
            if self.path == '/outer':
                body = (f'<iframe title="app" sandbox="allow-scripts allow-same-origin allow-forms" '
                        f'src="http://127.0.0.1:{self.server.server_port}/app"></iframe>').encode()
                headers = {}
            else:
                body = b'''<!doctype html><form id="form">
                  <input id="input" required><button id="add" type="submit">Add</button>
                  </form><output id="count">0</output><script>
                  window.submissions = 0;
                  document.querySelector('#form').addEventListener('submit', event => {
                    event.preventDefault();
                    document.querySelector('#count').textContent = String(++window.submissions);
                  });</script>'''
                headers = dict(HEADERS)
                headers['Content-Security-Policy'] = headers['Content-Security-Policy'].replace(
                    "frame-ancestors 'none'", f'frame-ancestors http://127.0.0.1:{self.server.server_port}')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', str(len(body)))
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            requests.append(('POST', self.path))
            self.send_response(405)
            self.end_headers()

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


@pytest.mark.parametrize('browser_name', ('chromium', 'firefox', 'webkit'))
@pytest.mark.parametrize('embedded', (False, True))
def test_local_form_events_validation_keyboard_and_transport(browser_name, embedded):
    with form_origin() as (url, requests), sync_playwright() as playwright:
        browser = getattr(playwright, browser_name).launch()
        try:
            page = browser.new_page()
            page.goto(url + ('/outer' if embedded else '/app'))
            frame = page.frames[-1]
            frame.locator('#add').click()
            assert frame.locator('#count').inner_text() == '0'  # Native required validation.
            frame.locator('#input').fill('真实输入')
            frame.locator('#add').click()
            assert frame.locator('#count').inner_text() == '1'
            frame.locator('#input').press('Enter')
            assert frame.locator('#count').inner_text() == '2'
            frame.evaluate("document.querySelector('#form').requestSubmit()")
            assert frame.locator('#count').inner_text() == '3'

            # Do not install request interception: observe the actual HTTP sink.
            for destination in (url + '/sink', 'http://127.0.0.1:1/external'):
                for method in ('get', 'post'):
                    seen = []
                    listener = lambda request: seen.append(request.url)
                    page.on('request', listener)
                    frame.evaluate('''({destination, method}) => {
                      window.violation = false;
                      document.addEventListener('securitypolicyviolation', () => window.violation = true,
                        {once: true});
                      const form = document.createElement('form');
                      form.action = destination; form.method = method;
                      const input = document.createElement('input');
                      input.name = 'payload'; input.value = 'must-stay-local';
                      form.append(input); document.body.append(form); form.requestSubmit();
                    }''', {'destination': destination, 'method': method})
                    frame.wait_for_function('() => window.violation === true')
                    assert frame.url == url + '/app'
                    assert not any('/sink' in item or '/external' in item for item in seen)
                    page.remove_listener('request', listener)
            assert not any('/sink' in path for _method, path in requests)
        finally:
            browser.close()
