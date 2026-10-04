"""Opt-in live provider/browser acceptance through normal authenticated APIs.

Creates a real acceptance account/project, incurs normal model usage, retains
the project for inspection, and logs out at completion. Secrets stay in memory.
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
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    base = args.base.rstrip('/')
    origin = f'{urlsplit(base).scheme}://{urlsplit(base).netloc}'
    evidence = {'base': base, 'steps': []}
    def record(name, **values):
        evidence['steps'].append({'step': name, **values})
        (args.output / 'evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
        print(name, json.dumps(values, ensure_ascii=False), flush=True)
    with httpx.Client(base_url=base, headers={'Origin': origin}, timeout=30) as client:
        def request(method, path, **kwargs):
            response = client.request(method, base + path, **kwargs)
            if response.status_code >= 400:
                raise RuntimeError(f'{method} {path}: HTTP {response.status_code}: {response.text[:300]}')
            return response.json()
        registration = request('POST', '/api/auth/register', json={
            'email': f'contract-acceptance-{secrets.token_hex(6)}@example.com',
            'password': secrets.token_urlsafe(24), 'name': '契约流程验收'})
        proof = registration.get('consoleProof')
        if proof:
            client.headers['X-Atom-Console-Proof'] = proof
        try:
            result = request('POST', '/api/projects', json={'prompt':
                '创建一个简洁的棋子动作练习页，有“落子”和“吃子”两个按钮，分别使用 data-testid="move" 和 data-testid="capture"。'
                '点击按钮增加对应计数并可重置。先不做音效。无需真实棋规、后端或登录。中文界面，适配手机。'})
            pid = result['project']['id']
            path = f'/api/projects/{pid}'
            evidence['projectId'] = pid
            def project():
                return request('GET', path)['project']
            def wait(status, *, changed=None, timeout=1200):
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    value = project()
                    if value['status'] in ('error', 'timed_out', 'cancelled', 'interrupted'):
                        raise RuntimeError(f"project ended {value['status']}: {value.get('latestRun', {}).get('error')}")
                    if value['status'] == status and (changed is None or value['contractVersion'] != changed):
                        return value
                    time.sleep(2)
                raise TimeoutError('live contract workflow exceeded budget')
            request('POST', path + '/plan', headers={'Idempotency-Key': secrets.token_hex(16)})
            first = wait('awaiting_approval')['contract']
            record('initial-contract', version=first['version'], snapshot=first['id'])
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                context = browser.new_context(viewport={'width': 1440, 'height': 1000})
                context.add_cookies([{'name': c.name, 'value': c.value, 'domain': c.domain,
                    'path': c.path, 'secure': c.secure, 'httpOnly': True} for c in client.cookies.jar])
                context.add_init_script('if (location.origin === ' + json.dumps(origin) + ') localStorage.setItem("atom.console.proof.v1", ' + json.dumps(proof or '') + ');')
                context.add_init_script('''(() => {
                  window.__audioStarts = 0; window.__audioPeak = 0;
                  const connect = AudioNode.prototype.connect;
                  AudioNode.prototype.connect = function(target, ...args) {
                    if (target instanceof AudioDestinationNode) {
                      const analyser = this.context.createAnalyser(); analyser.fftSize = 2048;
                      const samples = new Float32Array(analyser.fftSize);
                      connect.call(this, analyser, ...args); connect.call(analyser, target);
                      setInterval(() => { analyser.getFloatTimeDomainData(samples);
                        for (const value of samples) window.__audioPeak = Math.max(window.__audioPeak, Math.abs(value)); }, 5);
                      return target;
                    }
                    return connect.call(this, target, ...args);
                  };
                  for (const name of ['AudioContext', 'webkitAudioContext']) {
                    const Type = window[name]; if (!Type || Type.prototype.__contractObserved) continue;
                    Type.prototype.__contractObserved = true;
                    for (const method of ['createOscillator', 'createBufferSource']) {
                      const original = Type.prototype[method];
                      Type.prototype[method] = function(...args) {
                        const node = original.apply(this, args), start = node.start;
                        node.start = function(...values) { window.__audioStarts++; return start.apply(this, values); };
                        return node;
                      };
                    }
                  }
                  const play = HTMLMediaElement.prototype.play;
                  HTMLMediaElement.prototype.play = function(...args) { window.__audioStarts++; return play.apply(this, args); };
                })();''')
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(base + f'/app/p/{pid}')
                page.get_by_role('tab', name='契约', exact=True).click()
                changes = [
                    '增加真实落子与吃子音效，两种音效需要有明显不同。用 Web Audio 在用户点击 data-testid="move" 和 data-testid="capture" 时实际播放，不能只显示文字。将音效加入契约并移除旧的音效排除项。',
                    '再增加静音切换按钮 data-testid="mute"，默认开启声音，第一次点击静音后落子与吃子都不发声，再次点击恢复声音。保留原有计数、重置和两种音效。',
                ]
                latest = first
                for index, message in enumerate(changes, 1):
                    note = page.get_by_label('顺手微调（可选）')
                    note.fill(message)
                    expect(page.get_by_role('button', name='开始构建', exact=True)).to_be_disabled()
                    page.get_by_role('button', name='继续微调', exact=True).click()
                    updated = wait('awaiting_approval', changed=latest['id'])
                    latest = updated['contract']
                    assert message in latest['document']['notes']
                    assert not updated['files'], 'refinement wrote application files'
                    expect(note).to_have_value('', timeout=15000)
                    (args.output / f'contract-{latest["version"]}.json').write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding='utf-8')
                    record('refined', iteration=index, version=latest['version'], snapshot=latest['id'], requirements=len(latest['document']['requirements']))
                history = page.get_by_role('region', name='契约历史', exact=True)
                expect(history.get_by_role('listitem')).to_have_count(3)
                history.get_by_role('listitem').last.get_by_role('button', name='预览', exact=True).click()
                expect(page.get_by_role('region', name='契约版本 1 预览', exact=True)).to_be_visible()
                assert project()['contractVersion'] == latest['id']
                page.get_by_role('button', name='关闭预览', exact=True).click()
                history.get_by_role('listitem').last.get_by_role('button', name='恢复此版本', exact=True).click()
                page.get_by_role('button', name='确认恢复', exact=True).click()
                restored = wait('awaiting_approval', changed=latest['id'])['contract']
                assert restored['document'] == first['document']
                page.reload()
                page.get_by_role('tab', name='契约', exact=True).click()
                assert project()['contractVersion'] == restored['id']
                record('restored-and-reloaded', version=restored['version'], source=first['id'])
                # Return to the sound-enabled version using the same visible history controls.
                row = page.get_by_role('region', name='契约历史', exact=True).get_by_role('listitem').filter(has=page.get_by_text('版本 3', exact=True))
                row.get_by_role('button', name='恢复此版本', exact=True).click()
                page.get_by_role('button', name='确认恢复', exact=True).click()
                restored_sound = wait('awaiting_approval', changed=restored['id'])['contract']
                assert restored_sound['document'] == latest['document']
                page.screenshot(path=str(args.output / 'desktop-contract.png'), full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(args.output / 'mobile-contract.png'), full_page=True)
                page.set_viewport_size({'width': 1440, 'height': 1000})
                page.get_by_role('button', name='开始构建', exact=True).click()
                ready = wait('ready', timeout=3700)
                assert ready['contractVersion'] == restored_sound['id'] and ready['files']
                record('built', revision=ready['revisionId'], snapshot=ready['contractVersion'])
                page.get_by_role('tab', name='预览', exact=True).click()
                frame = page.frame_locator('iframe').first
                frame.get_by_test_id('move').wait_for(timeout=60000)
                preview = next(f for f in page.frames if f != page.main_frame and f.locator('[data-testid="move"]').count())
                before = preview.evaluate('window.__audioPeak = 0; window.__audioStarts')
                frame.get_by_test_id('move').click()
                page.wait_for_timeout(300)
                move = preview.evaluate('window.__audioStarts')
                assert move > before and preview.evaluate('window.__audioPeak') > .001, 'move produced no audible audio output'
                preview.evaluate('window.__audioPeak = 0')
                frame.get_by_test_id('capture').click()
                page.wait_for_timeout(300)
                capture = preview.evaluate('window.__audioStarts')
                assert capture > move and preview.evaluate('window.__audioPeak') > .001, 'capture produced no audible audio output'
                page.wait_for_timeout(500)
                preview.evaluate('window.__audioPeak = 0')
                frame.get_by_test_id('mute').click()
                frame.get_by_test_id('move').click(); frame.get_by_test_id('capture').click()
                page.wait_for_timeout(300)
                muted = preview.evaluate('window.__audioStarts')
                assert preview.evaluate('window.__audioPeak') < .0001, 'muted actions still produce audible output'
                frame.get_by_test_id('mute').click()
                frame.get_by_test_id('move').click()
                page.wait_for_timeout(300)
                assert preview.evaluate('window.__audioStarts') > muted and preview.evaluate('window.__audioPeak') > .001
                assert not errors, errors
                page.screenshot(path=str(args.output / 'generated-audio.png'), full_page=True)
                record('real-browser-audio', moveStarts=move-before, captureStarts=capture-move, mutedStarts=muted-capture, pageErrors=len(errors))
                context.close(); browser.close()
        finally:
            request('POST', '/api/auth/logout')
    record('passed')


if __name__ == '__main__':
    main()
