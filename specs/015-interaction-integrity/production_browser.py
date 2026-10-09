"""Real HTTPS production previews, with credentials only in piped memory.

A disposable console-origin harness embeds the actual live preview response;
this proves delivery rather than claiming the colleague's logged-in UI session.
The built workspace wrapper is separately accepted by its browser regression.
"""
import argparse
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright
from replay import exercise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--old-policy', action='store_true')
    args = parser.parse_args()
    access = json.load(sys.stdin)
    results = []
    with sync_playwright() as playwright:
        for engine in ('chromium', 'firefox', 'webkit'):
            browser = getattr(playwright, engine).launch()
            try:
                for row in access['previews']:
                    for embedded in (False, True):
                        context = browser.new_context()  # TLS verification stays enabled.
                        try:
                            origin = f'{urlsplit(row["url"]).scheme}://{urlsplit(row["url"]).netloc}'
                            context.add_cookies([{'name': row['cookieName'], 'value': row['cookie'],
                                'url': origin, 'secure': True, 'httpOnly': True, 'sameSite': 'Lax'}])
                            page = context.new_page()
                            responses = []
                            page.on('response', lambda response: responses.append(response)
                                    if response.url == row['url'] else None)
                            if embedded:
                                harness = access['console'] + '/atom/__interaction_acceptance__'
                                flags = 'allow-scripts allow-same-origin' + ('' if args.old_policy else ' allow-forms')
                                page.route(harness, lambda route: route.fulfill(content_type='text/html',
                                    body=f'<iframe title="app" sandbox="{flags}" src="{row["url"]}"></iframe>'))
                                page.goto(harness)
                                frame = page.frames[-1]
                            else:
                                page.goto(row['url']); frame = page.main_frame
                            frame.locator('body').wait_for(state='visible')
                            assert responses and responses[0].status == 200
                            headers = responses[0].all_headers()
                            assert headers['x-atom-revision'] == row['revision']
                            csp = headers['content-security-policy']
                            assert "form-action 'none'" in csp and "connect-src 'none'" in csp
                            assert ('allow-forms' in csp) is (not args.old_policy)
                            result = exercise(frame, lambda: frame.goto(row['url']), old=args.old_policy)
                            safe = {key: row[key] for key in ('project', 'revision', 'artifact', 'viewId')}
                            results.append({**safe, 'engine': engine, 'embedded': embedded, 'tlsVerified': True, **result})
                        finally:
                            context.close()
            finally:
                browser.close()
    args.output.write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(json.dumps({'scenarios': len(results), 'oldPolicy': args.old_policy,
                      'result': 'passed', 'receipt': str(args.output)}))


if __name__ == '__main__':
    main()
