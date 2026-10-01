"""Real Chromium policy tests with local HTTPS attack fixtures.

Uses production content headers, not production artifact/authentication plumbing.
Ephemeral self-signed TLS is accepted only by this disposable browser context.
"""
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import ssl
import sys
from tempfile import TemporaryDirectory
from threading import Thread

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.content_service import HEADERS

CONSOLE = 'console.atom-console.test'
CONTENT = 'release-a.atom-content.test'
SIBLING = 'release-b.atom-content.test'


def certificate(directory):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, CONSOLE)])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(hours=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(host) for host in
                (CONSOLE, CONTENT, SIBLING)]), critical=False).sign(key, hashes.SHA256()))
    key_path, cert_path = directory / 'key.pem', directory / 'cert.pem'
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path


def main():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            self.do_GET()

        def do_GET(self):
            host = self.headers.get('Host', '').split(':')[0]
            requests.append((host, self.path, self.command, self.headers.get('Cookie', '')))
            if host == CONSOLE:
                body = b'<h1>Console fixture</h1><script>localStorage.setItem("console-secret","fixture-secret")</script>'
            elif self.path == '/style.css':
                body = b'h1 { color: rgb(12, 34, 56); }'
            elif self.path == '/worker.js':
                body = b'self.postMessage("started");'
            elif self.path == '/sw.js':
                body = b'self.addEventListener("install",()=>self.skipWaiting());'
            elif host in (CONTENT, SIBLING):
                body = ('''<link rel="stylesheet" href="/style.css"><h1>Content fixture</h1>
<script>
window.findings={violations:[],cookie:document.cookie,secret:localStorage.getItem('console-secret')};
document.addEventListener('securitypolicyviolation',e=>findings.violations.push(e.effectiveDirective));
window.probe=async consoleOrigin=>{
  findings.secure=isSecureContext;
  try { findings.openerSecret=opener.localStorage.getItem('console-secret'); }
  catch(e) { findings.openerBlocked=true; }
  try { await fetch(consoleOrigin+'/probe-fetch',{method:'POST',credentials:'include'}); findings.fetchAllowed=true; }
  catch(e) { findings.fetchBlocked=true; }
  try {
    await Promise.race([
      new Promise((resolve,reject)=>{const worker=new Worker('/worker.js');
        worker.onmessage=()=>{worker.terminate();resolve();};
        worker.onerror=()=>{worker.terminate();reject(new Error('worker_rejected'));};}),
      new Promise((_,reject)=>setTimeout(()=>reject(new Error('probe_timeout')),2000))]);
    findings.workerAllowed=true;
  } catch(e) { if(e.message==='probe_timeout')throw e; findings.workerBlocked=true; }
  try { await navigator.serviceWorker.register('/sw.js'); findings.swAllowed=true; }
  catch(e) { findings.swBlocked=true; }
  findings.popupBlocked=window.open(consoleOrigin+'/probe-popup')===null;
  const image=new Image(); image.src=consoleOrigin+'/probe-image';document.body.append(image);
  const script=document.createElement('script');script.src=consoleOrigin+'/probe-script';document.body.append(script);
  const form=document.createElement('form');form.method='POST';form.action=consoleOrigin+'/probe-form';
  document.body.append(form);form.submit();
};
</script>''').encode()
            else:
                self.send_error(404)
                return
            self.send_response(200)
            if host in (CONTENT, SIBLING) and self.path != '/control':
                for name, value in HEADERS.items():
                    self.send_header(name, value)
            if host == CONSOLE:
                self.send_header('Set-Cookie', '__Host-fixture=console-only; Secure; HttpOnly; Path=/; SameSite=Lax')
            media = 'text/css' if self.path.endswith('.css') else 'application/javascript' if self.path.endswith('.js') else 'text/html'
            self.send_header('Content-Type', media)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    with TemporaryDirectory(prefix='atom-content-browser-') as temporary:
        cert, key = certificate(Path(temporary))
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(cert, key)
        server.socket = tls.wrap_socket(server.socket, server_side=True)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(args=['--no-proxy-server',
                    '--host-resolver-rules=' + ','.join(f'MAP {host} 127.0.0.1' for host in (CONSOLE, CONTENT, SIBLING))])
                context = browser.new_context(ignore_https_errors=True)
                context.set_default_timeout(5000)
                origin = lambda host: f'https://{host}:{server.server_port}'
                console_page = context.new_page()
                console_page.goto(origin(CONSOLE))
                assert console_page.evaluate('localStorage.getItem("console-secret")') == 'fixture-secret'
                assert any(cookie['name'] == '__Host-fixture' for cookie in context.cookies(origin(CONSOLE)))
                with console_page.expect_popup() as opened:
                    console_page.evaluate('(url)=>window.open(url)', origin(CONTENT))
                content_page = opened.value
                content_page.wait_for_load_state()
                assert content_page.locator('h1').inner_text() == 'Content fixture'
                assert content_page.locator('h1').evaluate('el=>getComputedStyle(el).color') == 'rgb(12, 34, 56)'
                with content_page.expect_console_message(predicate=lambda message:
                        'form submission' in message.text and 'sandboxed' in message.text):
                    content_page.evaluate('(url)=>probe(url)', origin(CONSOLE))
                content_page.wait_for_function("['connect-src','worker-src','img-src','script-src-elem'].every(x=>findings.violations.includes(x))")
                findings = content_page.evaluate('findings')
                assert findings['secure']
                assert findings['cookie'] == '' and findings['secret'] is None
                assert findings['openerBlocked'] and not findings.get('openerSecret')
                assert findings['fetchBlocked'] and not findings.get('fetchAllowed')
                assert findings['workerBlocked'] and not findings.get('workerAllowed')
                assert findings['swBlocked'] and not findings.get('swAllowed')
                assert findings['popupBlocked']
                assert content_page.url == origin(CONTENT) + '/'
                content_page.evaluate('localStorage.setItem("release-only","a")')
                sibling = context.new_page()
                sibling.goto(origin(SIBLING))
                assert sibling.evaluate('localStorage.getItem("release-only")') is None
                assert not [r for r in requests if r[1].startswith('/probe-') or r[1] in ('/worker.js', '/sw.js')]
                assert not [r for r in requests if r[0] in (CONTENT, SIBLING) and '__Host-fixture' in r[3]]
                with console_page.expect_console_message(predicate=lambda message: 'frame-ancestors' in message.text):
                    console_page.evaluate('url=>{const frame=document.createElement("iframe");frame.src=url;document.body.append(frame)}', origin(CONTENT))
                # Positive controls: the same network/worker actually function
                # when this fixture deliberately omits the production policy.
                control=context.new_page()
                control.goto(origin(CONTENT)+'/control')
                control.evaluate('url=>fetch(url+"/probe-control",{method:"POST",mode:"no-cors"})', origin(CONSOLE))
                assert any(r[0]==CONSOLE and r[1]=='/probe-control' and r[2]=='POST' for r in requests)
                assert control.evaluate('''()=>Promise.race([
                    new Promise((resolve,reject)=>{const worker=new Worker('/worker.js');
                      worker.onmessage=e=>{worker.terminate();resolve(e.data)};
                      worker.onerror=()=>reject(new Error('worker_control_failed'))}),
                    new Promise((_,reject)=>setTimeout(()=>reject(new Error('control_timeout')),2000))])''')=='started'
                print(json.dumps({'browser': browser.version, 'scope': 'local HTTPS production-header policy fixtures',
                    'findings': findings, 'crossReleaseStorageIsolated': True, 'consoleCookieNotSent': True,
                    'framingBlocked': True, 'formBlocked': True, 'networkAndWorkerControlsPassed': True}))
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


if __name__ == '__main__':
    main()
