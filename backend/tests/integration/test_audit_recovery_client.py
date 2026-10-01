import asyncio
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import uvicorn

from app.sandbox.audit_recovery_client import AuditRecoveryClient
from app.sandbox.client import BrokerClientError
from app.audit_archive import decode_archive
from test_audit_recovery_http import recovery, planned, reader, audited_release, release, ledger, legacy, IMAGE

pytestmark = pytest.mark.skipif(not IMAGE,reason='requires explicit pinned sandbox image')


def test_actual_loopback_client_fixed_worker_full_result(recovery):
    app,config,archive,_,plan = recovery
    sock = socket.socket()
    sock.bind(('127.0.0.1',0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False))
    worker = threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True)
    worker.start()
    try:
        deadline = time.monotonic()+10
        while not server.started and worker.is_alive() and time.monotonic()<deadline: time.sleep(.02)
        assert server.started
        async def run():
            async with AuditRecoveryClient(f'http://127.0.0.1:{port}',config.admin_token,
                    expected_image=IMAGE,expected_policy_digest=app.state.lifecycle.driver.policy_digest) as client:
                result = await client.recover(archive.payload,expected_sha256=archive.sha256)
                assert result['result']['events'] == [item['event'] for item in plan['items']]
                assert result['image'] == IMAGE
        asyncio.run(run())
        assert not app.state.lifecycle.driver.owned_inventory()
    finally:
        server.should_exit = True
        worker.join(20)
        sock.close()
        assert not worker.is_alive()


@pytest.mark.parametrize('fault',['image','policy','attempt','protocol','field','bool','extra','duplicate','oversize','redirect','encoding'])
def test_client_rejects_untrusted_wire_results(recovery,fault):
    _,config,archive,_,_ = recovery
    decoded = decode_archive(archive.payload,expected_sha256=archive.sha256)
    value = dict(protocol='audit-recovery-v2',image=IMAGE,policy_digest='a'*64,attempt_id='b'*32,
        result=dict(archive_sha256=archive.sha256,manifest=decoded['manifest'],events=decoded['events'],
                    recovery_target='isolated_memory_database',deletion_authorized=False))
    if fault=='image': value['image']='sha256:'+'f'*64
    elif fault=='policy': value['policy_digest']='f'*64
    elif fault=='attempt': value['attempt_id']='bad'
    elif fault=='protocol': value['protocol']='audit-recovery-v1'
    elif fault=='field': value['result']['events'][0]['scope_id']='other'
    elif fault=='bool': value['result']['events'][0]['schema_version']=True
    elif fault=='extra': value['unverified']=True
    payload = json.dumps(value,separators=(',',':')).encode()
    if fault=='duplicate': payload=payload.replace(b'"protocol":',b'"protocol":"audit-recovery-v2","protocol":',1)
    if fault=='oversize': payload=b'x'*264193
    seen=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            seen.append((self.path,self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(307 if fault=='redirect' else 200)
            self.send_header('content-type','application/json')
            self.send_header('content-length',str(len(payload)))
            if fault=='redirect': self.send_header('location','/must-not-follow')
            if fault=='encoding': self.send_header('content-encoding','gzip')
            self.end_headers()
            try:self.wfile.write(payload)
            except (BrokenPipeError,ConnectionResetError):pass
    server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    worker = threading.Thread(target=server.serve_forever,daemon=True)
    worker.start()
    try:
        async def run():
            async with AuditRecoveryClient(f'http://127.0.0.1:{server.server_port}',config.admin_token,
                    expected_image=IMAGE,expected_policy_digest='a'*64) as client:
                with pytest.raises(BrokerClientError):
                    await client.recover(archive.payload,expected_sha256=archive.sha256)
        asyncio.run(run())
        assert seen == [('/v1/admin/audit/recover',archive.payload)]
    finally:
        server.shutdown();worker.join(5);server.server_close()
