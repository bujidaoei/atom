"""Opt-in real Docker/Chromium boundary checks for the separate verifier image."""
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import subprocess
from uuid import uuid4

import pytest

from app.snapshots import verify_snapshot
from app.verification_contract import capture_contract


IMAGE = os.environ.get('ATOM_VERIFIER_TEST_IMAGE')
pytestmark = pytest.mark.skipif(not IMAGE, reason='requires pinned verifier image and Docker')
PROFILE = Path(__file__).resolve().parents[3] / 'deploy' / 'verifier-seccomp.json'


def _input(files, checks):
    ordered = sorted(files.items())
    manifest = json.dumps({'version': 1, 'files': [
        {'path': name, 'size': len(body), 'sha256': hashlib.sha256(body).hexdigest()}
        for name, body in ordered]}, sort_keys=True, separators=(',', ':')).encode()
    payload = b'ATOMSNAP1\n' + struct.pack('>I', len(manifest)) + manifest
    payload += b''.join(body for _, body in ordered)
    contract = capture_contract([{'key': 'page', 'title': 'Page', 'detail': '', 'checks': checks}])
    job = {'routeId': 'a' * 32, 'artifactKey': hashlib.sha256(payload).hexdigest(),
           'snapshotRevision': verify_snapshot(io.BytesIO(payload)).revision,
           'artifactSize': len(payload), 'contractDigest': contract.digest, 'budgetSeconds': 20}
    fields = (json.dumps(job, separators=(',', ':')).encode(), contract.canonical, payload)
    wire = b''.join(struct.pack('>I', len(field)) + field for field in fields)
    return job, wire


def _run(data=None, *, script=None, root=None):
    name = 'atom-verifier-test-' + uuid4().hex
    command = ['docker', 'run', '--rm', '--init', '--name', name,
               '--network', 'none', '--read-only', '--tmpfs', '/tmp:rw,nosuid,size=128m',
               '--shm-size', '256m', '--memory', '1g', '--cpus', '1.5', '--pids-limit', '128',
               '--cap-drop', 'ALL', '--cap-add', 'SYS_CHROOT',
               '--security-opt', 'no-new-privileges',
               '--security-opt', f'seccomp={PROFILE}']
    if data is not None:
        command.append('-i')
    if script is not None:
        command.extend(['--mount', f'type=bind,source={root.resolve()},target=/input,readonly'])
        command.extend(['--entrypoint', 'python'])
    command.append(IMAGE)
    if script is not None:
        command.append('/input/' + script)
    try:
        return subprocess.run(command, input=data, capture_output=True, timeout=60, check=False)
    finally:
        subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=10, check=False)


def test_container_observes_only_exact_snapshot(tmp_path):
    job, wire = _input({'index.html': b'<h1 id="title">Pinned</h1><script src="/app.js"></script>',
                        'app.js': b'document.querySelector("#title").textContent += " artifact"'},
                       [{'type': 'text', 'selector': '#title', 'contains': 'Pinned artifact'}])
    result = _run(wire)
    assert result.returncode == 0, result.stderr.decode(errors='replace')[-500:]
    envelope = json.loads(result.stdout)
    assert {name: envelope[name] for name in job if name in envelope} == {
        name: job[name] for name in ('routeId', 'artifactKey', 'snapshotRevision', 'artifactSize', 'contractDigest')}
    assert envelope['report']['results'] == [
        {'key': 'page', 'checkIndex': 0, 'passed': True, 'note': 'observed'}]
    report = json.dumps(envelope['report'], ensure_ascii=False, sort_keys=True,
                        separators=(',', ':')).encode()
    assert hashlib.sha256(report).hexdigest() == envelope['reportDigest']


def test_container_denies_tampered_artifact_and_cross_origin(tmp_path):
    _job, wire = _input({'index.html': b'<h1>Original</h1>'},
                        [{'type': 'exists', 'selector': 'h1'}])
    failed = _run(wire[:-1] + b'X')
    assert failed.returncode != 0 and not failed.stdout.strip()
    assert b'verifier_worker_failed' in failed.stderr

    trailing = _run(wire + b'extra')
    assert trailing.returncode != 0 and not trailing.stdout.strip()

    _job, wire = _input({'index.html': b'''<button id="go">Go</button><span id="ready">Ready</span>
        <script>document.querySelector('#go').onclick=()=>fetch('https://example.com/escape')
        .catch(()=>{});</script>'''},
        [{'type': 'flow', 'selector': '#go', 'expect': '#ready'}])
    observed = _run(wire)
    assert observed.returncode == 0, observed.stderr.decode(errors='replace')[-500:]
    assert json.loads(observed.stdout)['report']['results'][0] == {
        'key': 'page', 'checkIndex': 0, 'passed': False, 'note': 'content_policy_denied'}


@pytest.mark.parametrize('action,extra', [
    ("fetch('https://example.com/escape').catch(()=>{})", {}),
    ("new WebSocket('wss://example.com/socket')", {}),
    ("{const frame=document.createElement('iframe');frame.src='https://example.com/escape';document.body.append(frame)}", {}),
    ("window.open('https://example.com/escape','_blank')", {}),
    ("{const worker=new Worker('/worker.js');worker.postMessage('go')}",
     {'worker.js': b"self.onmessage=()=>fetch('https://example.com/escape').catch(()=>{})"}),
])
def test_container_malicious_page_cannot_escape_or_pass(action, extra):
    page = ('''<button id="go">Go</button><span id="ready" hidden>Ready</span>
      <script>document.querySelector('#go').onclick=()=>{ %s;
      setTimeout(()=>document.querySelector('#ready').hidden=false,350) }</script>''' % action).encode()
    _job, wire = _input({'index.html': page, **extra},
                        [{'type': 'flow', 'selector': '#go', 'expect': '#ready'}])
    observed = _run(wire)
    assert observed.returncode == 0, observed.stderr.decode(errors='replace')[-500:]
    assert json.loads(observed.stdout)['report']['results'][0] == {
        'key': 'page', 'checkIndex': 0, 'passed': False, 'note': 'content_policy_denied'}


def test_container_chromium_uses_nested_user_namespace(tmp_path):
    root = tmp_path / 'sandbox'
    root.mkdir(mode=0o755)
    probe = root / 'probe.py'
    probe.write_text('''import os
from pathlib import Path
from playwright.sync_api import sync_playwright
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(chromium_sandbox=True)
    try:
        page = browser.new_page()
        page.set_content('<h1>Actual browser</h1>')
        assert page.locator('h1').inner_text() == 'Actual browser'
        worker_ns = os.readlink('/proc/self/ns/user')
        nested = False
        for process in Path('/proc').iterdir():
            if not process.name.isdigit():
                continue
            try:
                if b'chrome-headless-shell' in (process / 'cmdline').read_bytes():
                    nested |= os.readlink(process / 'ns/user') != worker_ns
            except OSError:
                pass
        assert nested, 'Chromium renderer did not enter a nested user namespace'
        print('nested_chromium_user_namespace')
    finally:
        browser.close()
''')
    probe.chmod(0o644)
    result = _run(script='probe.py', root=root)
    assert result.returncode == 0, result.stderr.decode(errors='replace')[-500:]
    assert result.stdout.strip() == b'nested_chromium_user_namespace'
