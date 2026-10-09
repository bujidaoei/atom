"""The observer reads actual verified snapshot bytes through a loopback socket."""
import hashlib
import http.client
import io
import json
import struct
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest
from playwright.sync_api import sync_playwright

from app.artifacts import Artifact
from app.content_policy import GENERATED_CONTENT_HEADERS
from app.snapshots import verify_snapshot
from app.verification_contract import capture_contract
from app.verification_observer import observe_contract
from app.verification_origin import OriginError, pinned_snapshot_origin


def snapshot(files):
    ordered = sorted(files.items())
    manifest = json.dumps({'version': 1, 'files': [
        {'path': name, 'size': len(body), 'sha256': hashlib.sha256(body).hexdigest()}
        for name, body in ordered]}, sort_keys=True, separators=(',', ':')).encode()
    payload = b'ATOMSNAP1\n' + struct.pack('>I', len(manifest)) + manifest
    payload += b''.join(body for _, body in ordered)
    return payload, Artifact(hashlib.sha256(payload).hexdigest(),
                             verify_snapshot(io.BytesIO(payload)).revision, len(payload))


def test_exact_snapshot_is_served_and_real_chromium_observes_it():
    payload, artifact = snapshot({'index.html': b'<h1 id="title">Pinned</h1><script src="/app.js"></script>',
                                  'app.js': b'document.querySelector("#title").textContent += " artifact"'})
    contract = capture_contract([{'key': 'page', 'title': 'Page', 'detail': '',
                                  'checks': [{'type': 'text', 'selector': '#title',
                                              'contains': 'Pinned artifact'}]}])
    with pinned_snapshot_origin(payload, artifact) as url:
        with urlopen(url, timeout=2) as response:
            for name, value in GENERATED_CONTENT_HEADERS.items():
                assert response.headers[name] == value
        assert urlopen(url + 'app.js', timeout=2).read() == b'document.querySelector("#title").textContent += " artifact"'
        port = int(url.rsplit(':', 1)[1].rstrip('/'))
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
        connection.request('GET', '/', headers={'Host': 'external.example'})
        assert connection.getresponse().status == 404
        connection.close()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                report = observe_contract(browser, contract, url)
            finally:
                browser.close()
        assert report.total == report.passed == 1
        for path in ('../missing', 'missing', 'app.js?override=1'):
            with pytest.raises(HTTPError) as error:
                urlopen(url + path, timeout=2)
            assert error.value.code == 404


def test_changed_bytes_descriptor_or_reserved_path_fail_before_socket():
    payload, artifact = snapshot({'index.html': b'original'})
    with pytest.raises(OriginError, match='verifier_artifact_mismatch'):
        with pinned_snapshot_origin(payload[:-1] + b'X', artifact):
            pass
    with pytest.raises(OriginError, match='verifier_artifact_mismatch'):
        with pinned_snapshot_origin(payload, Artifact(artifact.key, '0' * 64, artifact.size)):
            pass
    payload, artifact = snapshot({'index.html': b'page', '_atom/config': b'secret'})
    with pytest.raises(ValueError, match='reserved_content_path'):
        with pinned_snapshot_origin(payload, artifact):
            pass


def test_origin_ends_with_scope():
    payload, artifact = snapshot({'index.html': b'page'})
    with pinned_snapshot_origin(payload, artifact) as url:
        assert urlopen(url, timeout=2).read() == b'page'
    with pytest.raises(Exception):
        urlopen(url, timeout=0.2)


@pytest.mark.parametrize('attempt', (
    "fetch('/api/escape').catch(()=>{});",
    "fetch('https://example.com/escape').catch(()=>{});",
    "const f=document.createElement('form');f.action='/escape';document.body.append(f);f.requestSubmit();",
))
def test_csp_denied_attempt_cannot_be_reported_as_passed(attempt):
    html = ('''<button id="go">Go</button><span id="ready" hidden>Ready</span>
      <script>document.querySelector('#go').onclick=()=>{''' + attempt + '''
      setTimeout(()=>document.querySelector('#ready').hidden=false,50);};</script>''').encode()
    payload, artifact = snapshot({'index.html': html})
    contract = capture_contract([{'key': 'page', 'title': 'Page', 'detail': '', 'checks': [
        {'type': 'flow', 'selector': '#go', 'expect': '#ready'}]}])
    with pinned_snapshot_origin(payload, artifact) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            report = json.loads(observe_contract(browser, contract, url).canonical)
        finally:
            browser.close()
    assert report['results'][0]['passed'] is False
    assert report['results'][0]['note'] == 'content_policy_denied'


def test_form_submit_flow_is_observed_under_delivery_csp():
    payload, artifact = snapshot({'index.html': b'''<form id="form">
      <input id="name" required><button id="go">Go</button></form>
      <span id="ready" hidden>Ready</span><script>
      document.querySelector('#form').onsubmit=e=>{e.preventDefault();
      document.querySelector('#ready').hidden=false;};</script>'''})
    contract = capture_contract([{'key': 'page', 'title': 'Page', 'detail': '', 'checks': [
        {'type': 'flow', 'selector': '#go', 'setup': [
            {'action': 'fill', 'selector': '#name', 'value': 'Actual input'}], 'expect': '#ready'}]}])
    with pinned_snapshot_origin(payload, artifact) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            report = observe_contract(browser, contract, url)
        finally:
            browser.close()
    assert report.total == report.passed == 1
