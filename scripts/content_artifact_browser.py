"""Real Chromium -> local TLS ingress -> Linux ContentService -> stored snapshot.

Requires ATOM_TEST_API_IMAGE (explicit installed sha256 image) and local Docker.
Fixture report seeds the release; this does not implement trusted verification.
"""
import base64
import argparse
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import mimetypes
import os
from pathlib import Path
import re
import ssl
import subprocess
from tempfile import TemporaryDirectory
from threading import Thread
import time
import uuid
from urllib.parse import urlsplit, parse_qs
import zipfile

from playwright.sync_api import sync_playwright
from content_browser_acceptance import certificate

ROOT = Path(__file__).resolve().parents[1]


def docker(*args):
    return subprocess.run(['docker',*args],capture_output=True,text=True,timeout=15,check=True).stdout.strip()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--reserved-path',action='store_true',help='Verify rejection of an actual conflicting artifact')
    parser.add_argument('--private-exchange',action='store_true',help='Exercise real HTTP exchange using fixture bootstrap/issuer')
    options=parser.parse_args()
    if options.private_exchange and options.reserved_path:parser.error('select one fixture mode')
    image = os.environ.get('ATOM_TEST_API_IMAGE','')
    if re.fullmatch(r'sha256:[0-9a-f]{64}',image) is None:
        raise ValueError('explicit_API_image_digest_required')
    archive = io.BytesIO()
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as bundle:
        for path in (ROOT/'backend/app').rglob('*.py'):
            bundle.write(path,'app/'+path.relative_to(ROOT/'backend/app').as_posix())
        bundle.write(ROOT/'scripts/content_artifact_fixture.py','fixture.py')
    bootstrap = """import base64,io,json,os,runpy,sys,zipfile
from pathlib import Path
root=Path('/tmp/code');root.mkdir()
payload=json.loads(sys.stdin.buffer.read())
os.environ['ATOM_FIXTURE_RESERVED_PATH']='1' if payload['conflict'] else '0'
os.environ['ATOM_FIXTURE_PRIVATE_EXCHANGE']='1' if payload['private'] else '0'
with zipfile.ZipFile(io.BytesIO(base64.b64decode(payload['code']))) as source:source.extractall(root)
sys.path.insert(0,str(root));runpy.run_path(str(root/'fixture.py'),run_name='__main__')
"""
    name = 'atom-content-browser-'+uuid.uuid4().hex
    with TemporaryDirectory(prefix='atom-artifact-browser-') as temporary:
        root = Path(temporary)
        with (root/'container.log').open('w+') as log:
            process = subprocess.Popen(['docker','run','--rm','--name',name,'-i','--read-only',
                '--user','1000:1000','--cap-drop=ALL','--security-opt=no-new-privileges',
                '--memory=512m','--pids-limit=128','--tmpfs','/tmp:rw,nosuid,nodev,size=256m,mode=1777',
                '--publish','127.0.0.1::8000','--workdir','/tmp',image,
                '/app/backend/.venv/bin/python','-I','-c',bootstrap],stdin=subprocess.PIPE,stdout=log,stderr=log)
            try:
                process.stdin.write(json.dumps({'code':base64.b64encode(archive.getvalue()).decode(),
                    'conflict':options.reserved_path,'private':options.private_exchange}).encode())
                process.stdin.close()
                deadline = time.monotonic()+20
                metadata = None
                while time.monotonic()<deadline:
                    if process.poll() is not None:
                        log.seek(0);raise RuntimeError(log.read())
                    try:
                        mapping=docker('port',name,'8000/tcp')
                        port=int(mapping.rsplit(':',1)[1])
                        connection=HTTPConnection('127.0.0.1',port,timeout=1)
                        connection.request('GET','/_fixture',headers={'Host':'fixture.invalid'})
                        response=connection.getresponse()
                        metadata=json.loads(response.read());connection.close()
                        break
                    except (OSError,ValueError,subprocess.CalledProcessError):
                        time.sleep(0.1)
                if metadata is None:raise RuntimeError('fixture_startup_timeout')
                observed=[]

                class Ingress(BaseHTTPRequestHandler):
                    def log_message(self,*_args):pass
                    def do_GET(self):
                        # Test ingress strips its ephemeral port while preserving
                        # the configured hostname; no forwarded authority is used.
                        host=self.headers.get('Host','').split(':')[0]
                        if host=='console.atom-console.test' and not self.path.startswith('/api/'):
                            relative=urlsplit(self.path).path.lstrip('/')
                            candidate=(ROOT/'frontend/dist'/relative).resolve()
                            dist=(ROOT/'frontend/dist').resolve()
                            if not candidate.is_relative_to(dist):self.send_error(404);return
                            if not candidate.is_file():candidate=dist/'index.html'
                            payload=candidate.read_bytes()
                            self.send_response(200);self.send_header('Content-Type',mimetypes.guess_type(candidate.name)[0] or 'application/octet-stream')
                            self.send_header('Referrer-Policy','no-referrer');self.send_header('Content-Length',str(len(payload)))
                            self.end_headers();self.wfile.write(payload);return
                        if host not in (metadata['host'],'console.atom-console.test'):
                            self.send_error(404);return
                        upstream=HTTPConnection('127.0.0.1',port,timeout=10)
                        try:
                            headers={'Host':host,'Sec-Fetch-Mode':self.headers.get('Sec-Fetch-Mode','')}
                            for field in ('Cookie','Content-Type','Content-Length','Origin','Sec-Fetch-Dest','Sec-Purpose','Purpose','X-Atom-Intent'):
                                if field in self.headers:headers[field]=self.headers[field]
                            # Exact local test origin maps to the configured 443 origin.
                            if headers.get('Origin')==f'https://{host}:{server.server_port}':
                                headers['Origin']='https://'+host
                            size=int(self.headers.get('Content-Length','0'))
                            if not 0<=size<=256:self.send_error(413);return
                            payload=self.rfile.read(size) if self.command=='POST' else None
                            upstream.request(self.command,self.path,body=payload,headers=headers)
                            response=upstream.getresponse();body=response.read()
                            observed.append((self.path,response.status,response.getheader('X-Atom-Revision')))
                            if host=='console.atom-console.test' and self.path.startswith('/api/content-access/') and response.status==200:
                                document=json.loads(body)
                                for field in ('url','contentOrigin'):
                                    if field in document:
                                        document[field]=document[field].replace('https://'+metadata['host'],f'https://{metadata["host"]}:{server.server_port}',1)
                                if 'url' in document:
                                    metadata['handoff']=urlsplit(document['url']).fragment
                                body=json.dumps(document).encode()
                            self.send_response(response.status)
                            for key,value in response.getheaders():
                                if key.lower() not in ('connection','transfer-encoding','server','date','content-length'):
                                    if key.lower()=='location' and value.startswith('https://console.atom-console.test/'):
                                        value=value.replace('https://console.atom-console.test/',f'https://console.atom-console.test:{server.server_port}/',1)
                                    self.send_header(key,value)
                            self.send_header('Content-Length',str(len(body)))
                            self.end_headers();self.wfile.write(body)
                        finally:upstream.close()
                    do_POST=do_GET

                cert,key=certificate(root,(metadata['host'],'console.atom-console.test'))
                server=ThreadingHTTPServer(('127.0.0.1',0),Ingress)
                tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(cert,key)
                server.socket=tls.wrap_socket(server.socket,server_side=True)
                thread=Thread(target=server.serve_forever,daemon=True);thread.start()
                try:
                    with sync_playwright() as playwright:
                        browser=playwright.chromium.launch(args=['--no-proxy-server',
                            '--host-resolver-rules=MAP '+metadata['host']+' 127.0.0.1, MAP console.atom-console.test 127.0.0.1'])
                        context=browser.new_context(ignore_https_errors=True)
                        page=context.new_page()
                        base=f'https://{metadata["host"]}:{server.server_port}'
                        if options.private_exchange:
                            assert page.goto(base+'/',timeout=5000).status==404
                            page.goto(base+'/_atom/bootstrap',wait_until='domcontentloaded',timeout=5000)
                            page.get_by_label('邮箱',exact=True).fill('owner@example.org')
                            page.get_by_role('button',name='继续',exact=True).click()
                            page.get_by_label('密码',exact=True).fill('Fixture-login-pass-713!')
                            page.get_by_role('button',name='登录',exact=True).click()
                            page.get_by_role('heading',name='确认要打开的版本').wait_for(timeout=10000)
                            page.get_by_role('heading',name='Fixture',exact=True).wait_for(timeout=5000)
                            assert not any(path=='/api/content-access/handoff' for path,_,_ in observed)
                            initial={c['name']:c for c in context.cookies()}
                            assert initial['__Host-atom_bootstrap']['httpOnly'] and initial['__Host-atom_console']['httpOnly']
                            for width,height in ((1440,900),(390,844)):
                                page.set_viewport_size({'width':width,'height':height})
                                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                                page.screenshot(path=str(ROOT/f'.logs/content-consent-{width}.png'),full_page=True)
                            context.route('**/_atom/exchange*',lambda route:route.abort(),times=1)
                            with page.expect_request('**/_atom/exchange*'):
                                page.get_by_role('button',name='确认并打开',exact=True).click(no_wait_after=True)
                            copied=browser.new_context(ignore_https_errors=True)
                            copied_page=copied.new_page()
                            copied_page.goto(base+'/_atom/exchange#'+metadata['handoff'],timeout=5000)
                            copied_page.get_by_text('Access could not be opened. Return to Atom and try again.',exact=True).wait_for(timeout=5000)
                            assert '#' not in copied_page.url
                            assert not any(c['name']=='__Host-atom_content' for c in copied.cookies())
                            copied.close()
                            page.goto(base+'/_atom/exchange#'+metadata['handoff'],timeout=5000)
                            page.wait_for_url(base+'/',wait_until='networkidle',timeout=15000)
                            jar={c['name']:c for c in context.cookies()}
                            assert '__Host-atom_bootstrap' not in jar
                            assert jar['__Host-atom_content']['httpOnly'] and jar['__Host-atom_content']['secure']
                            assert jar['__Host-atom_content']['sameSite']=='Lax'
                            assert page.evaluate('document.cookie')==''
                            assert all(metadata['handoff'] not in path for path,_,_ in observed)
                            response=None
                        else:
                            response=page.goto(base+'/',wait_until='networkidle',timeout=15000)
                        if options.reserved_path:
                            assert metadata['conflict'] and metadata['preflightChecked'] and response.status==503
                            assert page.locator('h1').count()==0
                            print(json.dumps({'browser':browser.version,'reservedArtifactRejected':True,'publicationPreflightRejected':True,'status':response.status,
                                'scope':'actual conflicting Linux snapshot denied before browser content execution'}))
                            browser.close()
                            return
                        assert page.locator('h1').inner_text()=='Actual immutable artifact'
                        loaded=page.evaluate('window.loaded || []')
                        assert sorted(loaded)==list(range(8)),{'loaded':loaded,'responses':observed}
                        styles=page.locator('h1').evaluate('el=>Array.from({length:8},(_,i)=>getComputedStyle(el).getPropertyValue("--asset-"+i).trim())')
                        assert styles==list(map(str,range(8))),styles
                        denied=page.goto(f'https://{metadata["host"]}:{server.server_port}/_atom/access',timeout=5000)
                        assert denied.status==404
                        assert all(status==200 and revision==metadata['revision'] for path,status,revision in observed
                                   if not path.startswith('/api/') and path not in ('/favicon.ico','/_atom/access','/_atom/exchange','/_atom/bootstrap') and not (options.private_exchange and status==404))
                        print(json.dumps({'browser':browser.version,'artifactRevision':metadata['revision'],
                            'scripts':len(loaded),'styles':len(styles),'privateExchange':options.private_exchange,'httpBootstrap':options.private_exchange,'realLoginAndConsent':options.private_exchange,'responses':observed,
                            'scope':'actual Linux artifact HTTP to Chromium through local test TLS ingress'}))
                        browser.close()
                finally:
                    server.shutdown();server.server_close();thread.join(timeout=3)
            finally:
                subprocess.run(['docker','rm','-f',name],capture_output=True,timeout=15)
                process.wait(timeout=15)


if __name__=='__main__':main()
