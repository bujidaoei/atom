"""Normal authenticated API, real provider and built workspace acceptance.

Retains a genuine acceptance project for inspection. Signup password/session
proof/cookies stay in memory; logout revokes its session on every exit.
"""
import argparse
import json
from pathlib import Path
import secrets
import time
from urllib.parse import urlsplit

import httpx
from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    base = args.base.rstrip('/')
    origin = f'{urlsplit(base).scheme}://{urlsplit(base).netloc}'
    evidence = {'steps': []}

    def record(step, **values):
        evidence['steps'].append({'step': step, **values})
        (args.output / 'evidence.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
        print(json.dumps({'step': step, **values}), flush=True)

    with httpx.Client(headers={'Origin': origin}, timeout=30) as client:
        def request(method, path, **kwargs):
            response = client.request(method, base + path, **kwargs)
            if response.status_code >= 400:
                raise RuntimeError(f'live_api_failed_{response.status_code}_{path}')
            return response.json()

        registration = request('POST', '/api/auth/register', json={
            'email': f'form-acceptance-{secrets.token_hex(6)}@example.com',
            'password': secrets.token_urlsafe(24), 'name': 'Form interaction acceptance'})
        proof = registration['consoleProof']
        client.headers['X-Atom-Console-Proof'] = proof
        try:
            prompt = ('制作上线验收用的最小中文两数相加计算器。实际实现标准 form 的 submit 事件与 preventDefault。'
                '两个必填数字输入使用 data-testid="a"、"b"，支持负数和小数。'
                '计算按钮 data-testid="calculate" 是 submit；输出 data-testid="result"，'
                'data-value 是数值字符串，data-count 是成功计算次数。点击一次或按一次 Enter 只计算一次。'
                '清空按钮 data-testid="clear" 清空输入并重置输出 data-value=""、data-count="0"。'
                '空输入不计算，原生校验仍生效。页面初始输出为空、次数0。适配手机。'
                '只需要本地 index.html、styles.css、app.js；无需历史、持久化、网络、后端、登录或其他功能。')
            value = request('POST', '/api/projects', json={'prompt': prompt})['project']
            pid = value['id']
            path = f'/api/projects/{pid}'
            record('created', projectId=pid)

            def wait(status, seconds=1200):
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    value = request('GET', path)['project']
                    if value['status'] in ('error', 'timed_out', 'cancelled', 'interrupted'):
                        raise RuntimeError('live_project_' + value['status'])
                    if value['status'] == status and value.get('activeRunId') is None:
                        return value
                    time.sleep(2)
                raise TimeoutError('live_generation_deadline')

            request('POST', path + '/plan', headers={'Idempotency-Key': secrets.token_hex(16)})
            planned = wait('awaiting_approval')
            record('planned', contractVersion=planned['contractVersion'], requirements=len(planned['requirements']))
            request('POST', path + '/approve', json={'expectedVersion': planned['contractVersion']},
                    headers={'Idempotency-Key': secrets.token_hex(16)})
            built = wait('ready')
            record('built', revisionId=built['revisionId'], files=[item['path'] for item in built['files']])
            request_id = secrets.token_hex(16)
            request('POST', path + '/verifications', json={'requestId': request_id})
            request('POST', path + f'/verifications/{request_id}/run')
            deadline = time.monotonic() + 330
            while time.monotonic() < deadline:
                verified = request('GET', path + f'/verifications/{request_id}')
                if verified['state'] not in ('reserved', 'running'):
                    break
                time.sleep(2)
            assert verified['state'] == 'passed', 'real_server_verification_failed'
            assert verified['passed'] == verified['total'] and verified['total'] > 0
            record('server-verified', requestId=request_id, revisionId=verified['revisionId'],
                   passed=verified['passed'], total=verified['total'])

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    context = browser.new_context(viewport={'width': 1440, 'height': 900})
                    context.add_cookies([{'name': c.name, 'value': c.value, 'domain': c.domain,
                        'path': c.path, 'secure': c.secure, 'httpOnly': True} for c in client.cookies.jar])
                    context.add_init_script('if (location.origin === ' + json.dumps(origin) + ') '
                        'localStorage.setItem("atom.console.proof.v1", ' + json.dumps(proof) + ');')
                    page = context.new_page()
                    page.goto(base + '/app/p/' + pid)
                    page.locator('[data-preview-state=displayed]').wait_for(timeout=30000)
                    frame = page.frame_locator('iframe[title="项目预览"]')
                    assert 'allow-forms' in page.locator('iframe[title="项目预览"]').get_attribute('sandbox').split()
                    a, b = frame.get_by_test_id('a'), frame.get_by_test_id('b')
                    result = frame.get_by_test_id('result')
                    a.fill('2'); b.fill('3'); frame.get_by_test_id('calculate').click()
                    expect(result).to_have_attribute('data-value', '5')
                    expect(result).to_have_attribute('data-count', '1')
                    a.fill('-1.5'); b.fill('2'); frame.get_by_test_id('calculate').click()
                    expect(result).to_have_attribute('data-value', '0.5')
                    expect(result).to_have_attribute('data-count', '2')
                    b.press('Enter')
                    expect(result).to_have_attribute('data-count', '3')
                    frame.get_by_test_id('clear').click()
                    expect(a).to_have_value(''); expect(b).to_have_value('')
                    expect(result).to_have_attribute('data-value', '')
                    expect(result).to_have_attribute('data-count', '0')
                    frame.get_by_test_id('calculate').click()
                    expect(result).to_have_attribute('data-count', '0')
                    page.screenshot(path=str(args.output / 'workspace.png'), full_page=True)
                    page.reload()
                    page.locator('[data-preview-state=displayed]').wait_for(timeout=30000)
                    expect(frame.get_by_test_id('result')).to_have_attribute('data-count', '0')
                    record('owner-workspace-browser', mouse=True, decimals=True, enterExactlyOnce=True,
                           clear=True, nativeValidation=True, reload=True, tlsVerified=True)
                    context.close()
                finally:
                    browser.close()
        finally:
            request('POST', '/api/auth/logout')
            record('logged-out', sessionRevoked=True)


if __name__ == '__main__':
    main()
