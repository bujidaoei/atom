import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import hashlib
import struct
import secrets
import threading

import pytest

from app.sandbox.client import BrokerClient, BrokerClientError
from app.sandbox.grants import Grant, GrantCodec


@pytest.mark.parametrize('body,status', [
    (b'{"alive":true,"ready":true}',200),
    (b'{"alive":true,"ready":false}',200),
    (b'{"alive":true,"ready":1}',200),
    (b'{"alive":true,"ready":true,"extra":true}',200),
    (b'{"alive":true,"ready":true}',503),
    (b'x'*1025,200),
])
def test_actual_readiness_requires_authenticated_exact_positive_response(body,status):
    admin=secrets.token_urlsafe(32)
    observed=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_GET(self):
            observed.append((self.path,self.headers.get('Authorization')))
            self.send_response(status)
            self.send_header('Content-Type','application/json')
            self.end_headers()
            self.wfile.write(body)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    async def scenario():
        async with BrokerClient(f'http://127.0.0.1:{server.server_port}',admin,GrantCodec(b'k'*32)) as client:
            if status==200 and body==b'{"alive":true,"ready":true}':
                await client.require_ready()
            else:
                with pytest.raises(BrokerClientError): await client.require_ready()
    try:
        asyncio.run(scenario())
        assert observed==[('/ready','Bearer '+admin)]
    finally:
        server.shutdown();server.server_close();thread.join(timeout=3)


@pytest.mark.parametrize('origin', ['http://example.com','http://localhost:80','https://user:secret@example.com',
    'https://example.com/path','https://example.com?x=1','https://example.com/#part','file:///tmp/socket'])
def test_invalid_origin_rejected_without_network(origin):
    with pytest.raises(BrokerClientError, match='invalid_broker_client_configuration'):
        BrokerClient(origin,secrets.token_urlsafe(32),GrantCodec(b'k'*32))


@pytest.mark.parametrize('case', ['redirect','malformed','oversized','wrong_scope','compressed','slow','slow_body'])
def test_actual_transport_rejects_uncertain_responses_without_retry(case):
    requests = []
    admin = secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def do_POST(self):
            requests.append(self.path)
            assert self.headers['Authorization'] == 'Bearer ' + admin
            self.rfile.read(int(self.headers['Content-Length']))
            if case == 'slow':
                threading.Event().wait(0.15)
            self.send_response(307 if case == 'redirect' else 202)
            if case == 'redirect':
                self.send_header('Location','/must-not-follow')
            self.send_header('Content-Type','application/json')
            if case == 'compressed':
                self.send_header('Content-Encoding','gzip')
            self.end_headers()
            if case == 'slow_body':
                threading.Event().wait(0.15)
            body = b'not json' if case == 'malformed' else b'x'*20000 if case == 'oversized' else json.dumps({
                'attempt_id':'a'*32,'state':'provisioning','deadline':999}).encode()
            try:
                self.wfile.write(body)
            except (BrokenPipeError,ConnectionResetError):
                pass
    server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread = threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    async def scenario():
        import time
        now = int(time.time())
        grant = Grant('g','o','p','r','a',1,'b'*64,now,now+120)
        async with BrokerClient(f'http://127.0.0.1:{server.server_port}',admin,GrantCodec(b'k'*32),timeout=0.05 if case.startswith('slow') else 3) as client:
            with pytest.raises(BrokerClientError) as raised:
                await client.provision(grant)
            assert admin not in str(raised.value) and '999' not in str(raised.value)
            if case.startswith('slow'):
                assert raised.value.code == 'broker_outcome_unknown'
    try:
        asyncio.run(scenario())
        assert requests == ['/v1/admin/provision']
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.mark.parametrize('case',['duplicate_header','raw_digest','semantic_digest','version','corrupt_archive'])
def test_export_integrity_rejects_actual_malformed_network_responses(case):
    manifest = b'{"files":[],"version":1}'
    payload = b'ATOMSNAP1\n' + struct.pack('>I',len(manifest)) + manifest
    revision = hashlib.sha256(manifest).hexdigest()
    if case == 'corrupt_archive':
        payload = payload[:-1]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            self.send_response(200)
            self.send_header('Content-Type','application/octet-stream')
            self.send_header('X-Atom-Attempt','a'*32)
            self.send_header('X-Atom-Export-Version','01' if case=='version' else '3')
            if case == 'duplicate_header':
                self.send_header('X-Atom-Export-Version','3')
            self.send_header('X-Atom-Revision','0'*64 if case=='semantic_digest' else revision)
            self.send_header('X-Atom-Artifact-Key','0'*64 if case=='raw_digest' else hashlib.sha256(payload).hexdigest())
            self.end_headers()
            self.wfile.write(payload)
    server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread = threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    async def scenario():
        import time
        now = int(time.time())
        grant = Grant('g','o','p','r','a',1,revision,now,now+120)
        async with BrokerClient(f'http://127.0.0.1:{server.server_port}',secrets.token_urlsafe(32),GrantCodec(b'k'*32)) as client:
            with pytest.raises(BrokerClientError):
                await client.export(grant,'a'*32)
    try:
        asyncio.run(scenario())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.mark.parametrize('change',[{'attempt_id':'b'*32},{'state':'ready'},{'version':True},
    {'revision':None},{'state':'quiescing','revision':'b'*64}])
def test_checkpoint_status_rejects_uncorrelated_network_evidence(change):
    import time
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
            self.wfile.write(json.dumps({'attempt_id':'a'*32,'state':'checkpointed','version':4,
                                        'revision':'b'*64,**change}).encode())
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    async def scenario():
        now=int(time.time())
        grant=Grant('g','o','p','r','a',1,'b'*64,now,now+120)
        async with BrokerClient(f'http://127.0.0.1:{server.server_port}',secrets.token_urlsafe(32),GrantCodec(b'k'*32)) as client:
            with pytest.raises(BrokerClientError,match='invalid_broker_response'):
                await client.checkpoint_status(grant,'a'*32)
    try: asyncio.run(scenario())
    finally:
        server.shutdown();server.server_close();thread.join(timeout=3)
