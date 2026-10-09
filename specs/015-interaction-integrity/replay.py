"""Replay captured original COS source under old/new delivery restrictions.

Reads the ignored operator capture, never edits originals or production data.
This is real artifact browser evidence, distinct from owner-session acceptance.
"""
import argparse
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
from threading import Thread
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from app.content_policy import GENERATED_CONTENT_HEADERS
from playwright.sync_api import sync_playwright


@contextmanager
def origin(files, old):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            if self.path == '/outer':
                flags = 'allow-scripts allow-same-origin' + ('' if old else ' allow-forms')
                body = f'<iframe title="app" sandbox="{flags}" src="/index.html"></iframe>'.encode()
                headers = {}
            else:
                name = self.path.lstrip('/') or 'index.html'
                if name not in files:
                    self.send_error(404)
                    return
                body = files[name].encode('utf-8')
                headers = dict(GENERATED_CONTENT_HEADERS)
                csp = headers['Content-Security-Policy'].replace(
                    "frame-ancestors 'none'", f'frame-ancestors http://127.0.0.1:{self.server.server_port}')
                headers['Content-Security-Policy'] = csp.replace(' allow-forms', '') if old else csp
            self.send_response(200)
            self.send_header('Content-Type', (mimetypes.guess_type(self.path)[0] or 'text/html') + '; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
        assert not thread.is_alive()


def exercise(frame, reload, *, old=False):
    def control(name):
        return frame.locator(f'[data-testid="{name}"]')

    if control('calc-btn').count():
        control('num-a-input').fill('2'); control('num-b-input').fill('3')
        control('calc-btn').click()
        click_result = control('result-value').get_attribute('data-value')
        if old:
            assert click_result in ('', '5')
            control('num-b-input').press('Enter')
            assert control('result-value').get_attribute('data-value') == '5'
            return {'kind': 'calculator', 'click': 'blocked' if click_result == '' else 'working', 'enter': '5'}
        assert click_result == '5'
        for op, a, b, answer in (('-', '2', '3', '-1'), ('*', '-1.5', '2', '-3'), ('/', '7', '2', '3.5')):
            control('operator-select').select_option(op)
            control('num-a-input').fill(a); control('num-b-input').fill(b); control('calc-btn').click()
            assert control('result-value').get_attribute('data-value') == answer
        control('num-b-input').fill('0'); control('calc-btn').click()
        assert control('error-msg').get_attribute('data-visible') == 'true'
        control('num-a-input').fill('invalid'); control('calc-btn').click()
        assert control('error-msg').get_attribute('data-visible') == 'true'
        control('history-item').first.click()
        assert control('num-a-input').input_value() == '7'
        assert control('num-b-input').input_value() == '2'
        control('calc-btn').click()
        assert control('result-value').get_attribute('data-value') == '3.5'
        control('clear-btn').click()
        assert control('num-a-input').input_value() == ''
        control('num-a-input').fill('-1.5'); control('num-b-input').fill('2'); control('num-b-input').press('Enter')
        assert control('result-value').get_attribute('data-value') == '0.5'
        assert control('history-item').count() == 5
        return {'kind': 'calculator', 'arithmetic_error_history_clear_enter': 'passed'}

    if control('todo-input').count():
        control('todo-input').fill('Write weekly report'); control('add-button').click()
        if old:
            count = control('todo-item').count()
            assert count in (0, 1)
            return {'kind': 'todo', 'click': 'blocked' if count == 0 else 'working', 'items': count}
        assert control('todo-item').count() == 1
        reload()
        assert control('todo-item').count() == 1
        control('todo-toggle').check()
        assert control('todo-item').get_attribute('data-completed') == 'true'
        control('todo-delete').click(); assert control('todo-item').count() == 0
        control('todo-input').fill('Keyboard task'); control('todo-input').press('Enter')
        assert control('todo-item').count() == 1
        return {'kind': 'todo', 'add_reload_complete_delete_enter': 'passed'}

    if control('item-input').count():
        control('item-input').fill('Lunch'); control('amount-input').fill('20'); control('add-btn').click()
        if old:
            count = control('expense-row').count()
            total = control('total-amount').get_attribute('data-total')
            assert (count, total) in ((0, '0'), (1, '20'))
            return {'kind': 'expense', 'click': 'blocked' if count == 0 else 'working', 'total': total}
        assert control('expense-row').count() == 1
        assert control('total-amount').get_attribute('data-total') == '20'
        reload(); assert control('expense-row').count() == 1
        control('delete-btn').click()
        assert control('total-amount').get_attribute('data-total') == '0'
        control('item-input').fill('Tea'); control('amount-input').fill('2.50'); control('amount-input').press('Enter')
        assert control('expense-row').count() == 1
        assert control('total-amount').get_attribute('data-total') == '2.5'
        return {'kind': 'expense', 'add_total_reload_delete_enter': 'passed'}

    # Existing direct-click keypad calculator is an independent regression.
    control('btn-2').click(); control('btn-add').click(); control('btn-3').click(); control('btn-equals').click()
    assert control('display').get_attribute('data-value') == '5'
    reload(); assert control('history-item').count() == 1
    control('btn-clear').click(); assert control('display').get_attribute('data-value') == '0'
    return {'kind': 'keypad', 'click_history_reload_clear': 'passed'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--old-policy', action='store_true')
    args = parser.parse_args()
    rows = json.loads(args.source.read_text(encoding='utf-8-sig'))
    results = []
    with sync_playwright() as playwright:
        for engine in ('chromium', 'firefox', 'webkit'):
            browser = getattr(playwright, engine).launch()
            try:
                for row in rows:
                    for embedded in (False, True):
                        with origin(row['files'], args.old_policy) as url:
                            context = browser.new_context()
                            page = context.new_page()
                            page.goto(url + ('/outer' if embedded else '/index.html'))
                            frame = page.frames[-1]
                            def reload():
                                if embedded:
                                    frame.goto(url + '/index.html')
                                else:
                                    page.reload()
                            result = exercise(frame, reload, old=args.old_policy)
                            results.append({'artifact': row['key'], 'engine': engine, 'embedded': embedded, **result})
                            context.close()
            finally:
                browser.close()
    args.output.write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(f'{len(results)} actual artifact browser scenarios passed; old_policy={args.old_policy}')


if __name__ == '__main__':
    main()
