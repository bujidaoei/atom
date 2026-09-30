"""Actual API orchestration through a host transport relay to the real Node server."""
import base64
import io
import json
import os
from pathlib import Path
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import uuid
import zipfile

import pytest

from app.sandbox.docker_driver import run_bounded
from test_revision_registration import running_broker

IMAGE = os.environ.get('ATOM_TEST_API_IMAGE')
pytestmark = pytest.mark.skipif(not IMAGE or not os.environ.get('ATOM_TEST_DOCKER_IMAGE'),
                               reason='requires explicit local API and sandbox image digests')


@pytest.mark.parametrize('valid,interrupt', [(True,None),(False,None),(None,None),(False,'cancel'),(False,'deadline'),(False,'deadline_checkpoint')])
def test_actual_orchestrator_leases_and_validates_registered_output(tmp_path, valid, interrupt):
    assert re.fullmatch(r'sha256:[0-9a-f]{64}', IMAGE)
    root=Path(__file__).resolve().parents[3]
    archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as bundle:
        for path in (root/'backend/app').rglob('*.py'):
            bundle.write(path,'app/'+path.relative_to(root/'backend/app').as_posix())
    name='atom-orchestration-test-'+uuid.uuid4().hex
    observed=[]
    # Measured Docker Desktop clock lead: retain strict production grant checks.
    with running_broker(tmp_path/'broker.db', provision_delay=1) as (lifecycle,broker,runner,config):
        class Relay(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_POST(self):
                if self.path.endswith('/cancel'):
                    self.send_response(200);self.end_headers();return
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                observed.append(body['runId'])
                assert body['lease']['runId']==body['runId']
                if valid is None:
                    self.close_connection=True
                    return
                code,port,err=run_bounded(['docker','port',name,'8767/tcp'])
                assert code==0,err.decode()
                runtime=root/'runtime'
                parameters={'lease':body['lease'],'request':body,'brokerOrigin':broker._origin,
                    'executionOrigin':'http://'+port.decode().strip(), 'outputFile':'notes.txt' if len(observed)>1 else 'index.html',
                    'outputText':'<h1>actual orchestrated output</h1>' if valid or interrupt else '', 'interrupt':interrupt}
                code,out,err=run_bounded(['node','--import',(runtime/'node_modules/tsx/dist/loader.mjs').as_uri(),
                    str(runtime/'scripts/test-server-execution.ts')],input_data=json.dumps(parameters).encode(),timeout=25)
                assert code==0,err.decode()
                response=json.loads(out)
                payload=''.join(json.dumps(line)+'\n' for line in response['lines']).encode()
                self.send_response(200);self.send_header('Content-Type','application/x-ndjson')
                self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        relay=ThreadingHTTPServer(('127.0.0.1',0),Relay)
        worker=threading.Thread(target=relay.serve_forever,daemon=True);worker.start()
        script=r'''
import asyncio,base64,io,json,os,sys,zipfile,sqlite3
from pathlib import Path
data=json.loads(sys.stdin.buffer.read())
code=Path('/tmp/code');code.mkdir()
with zipfile.ZipFile(io.BytesIO(base64.b64decode(data['code']))) as z:z.extractall(code)
sys.path.insert(0,str(code))
Path('/tmp/artifacts').mkdir(mode=0o700)
os.environ.update(ATOM_ENVIRONMENT='production',ATOM_SANDBOX_MODE='broker',ATOM_COOKIE_SECURE='true',
    ATOM_SECRET='synthetic-session-key-32-characters-long',ATOM_RUNTIME_TOKEN='synthetic-runtime-key-32-characters-long',
    ATOM_DATA_DIR='/tmp/data',ATOM_DB_PATH='/tmp/data/api.db',ATOM_ARTIFACT_DIR='/tmp/artifacts',
    ATOM_BROKER_ORIGIN='http://127.0.0.1:1',ATOM_BROKER_ADMIN_TOKEN=data['admin'],ATOM_BROKER_GRANT_KEY=data['key'],
    ATOM_COMPLETION_GRANT_KEY='c'*32,ATOM_LLM_API_KEY='synthetic-model-fixture-key',
    ATOM_LLM_BASE_URL='https://synthetic.invalid/v1',ATOM_RUNTIME_URL='http://127.0.0.1:1')
from app.main import app
if data['interrupt']=='deadline_checkpoint':
    @app.middleware('http')
    async def delayed_confirmation(request,call_next):
        response=await call_next(request)
        if request.url.path=='/v1/executions/complete':await asyncio.sleep(4.5)
        return response
from app.config import get_settings
from app.db import engine,session_scope
from app.models import Base,User,Project,Run
from app.migrations import migrate
from app.services.orchestrator import orchestrator
from app.services.runtime_client import RuntimeClient,GatewayConfig
from sqlalchemy import select
import uvicorn
Base.metadata.create_all(engine)
with session_scope() as s:
    s.add(User(id='owner',email='owner@example.invalid',name='Owner',password_hash='fixture'));s.flush()
    s.add(Project(id='p',user_id='owner',title='P',prompt='fixture'))
settings=get_settings();migrate(settings.db_path,Path('/tmp/data/backup.db'));settings.db_path.chmod(0o600)
if data['interrupt']:
    legacy=settings.projects_dir/'p'/'workspace';legacy.mkdir(parents=True)
    (legacy/'index.html').write_text('<h1>saved before interruption</h1>')
async def main():
    async def proxy(port):
        async def relay(reader,writer):
            upstream=None;tasks=[]
            try:
                other,upstream=await asyncio.open_connection('host.docker.internal',port)
                async def copy(source,dest):
                    while chunk:=await source.read(65536):dest.write(chunk);await dest.drain()
                tasks=[asyncio.create_task(copy(reader,upstream)),asyncio.create_task(copy(other,writer))]
                await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in tasks:task.cancel()
                await asyncio.gather(*tasks,return_exceptions=True);writer.close()
                if upstream:upstream.close()
        return await asyncio.start_server(relay,'127.0.0.1',0)
    broker=await proxy(data['broker']);runtime=await proxy(data['runtime'])
    settings.broker_origin='http://127.0.0.1:'+str(broker.sockets[0].getsockname()[1])
    settings.runtime_url='http://127.0.0.1:'+str(runtime.sockets[0].getsockname()[1])
    orchestrator._client=RuntimeClient()
    server=uvicorn.Server(uvicorn.Config(app,host='0.0.0.0',port=8767,log_level='error',access_log=False))
    serving=asyncio.create_task(server.serve())
    try:
        for _ in range(300):
            if server.started or serving.done():break
            await asyncio.sleep(0.02)
        assert server.started
        expected='cancelled' if data['interrupt']=='cancel' else 'timed_out' if data['interrupt'] else 'done' if data['valid'] else 'failed'
        if data['interrupt']:
            await orchestrator.start_build('p','owner',None)
            await asyncio.wait_for(orchestrator._jobs['p'],20)
            with session_scope() as s:
                recorded=s.scalar(select(Run).where(Run.project_id=='p'))
                observed_status=recorded.status
                assert s.get(Project,'p').status==expected
                assert not orchestrator.active('p')
        else:
            outcome=await orchestrator._turn('p','owner',role='alex',phase='build',
                gateway=GatewayConfig('https://synthetic.invalid','synthetic','test-model'),
                prompt='Write index.html and finish.',budget_seconds=1000 if data['valid'] else 40)
            assert outcome.failed==(data['valid'] is not True),outcome
            observed_status=outcome.status
        assert observed_status==expected,observed_status
        if data['valid']:
            # The second runtime writes only notes: index.html must survive from
            # the prior committed seed, since the legacy directory stays empty.
            outcome=await orchestrator._turn('p','owner',role='alex',phase='revise',
                gateway=GatewayConfig('https://synthetic.invalid','synthetic','test-model'),
                prompt='Write notes.txt and preserve the existing index.',budget_seconds=40)
            assert not outcome.failed and outcome.status=='done',outcome
        resources=app.state.execution
        workspace=resources.repository.find_workspace('owner','p')
        head=resources.repository.current_revision('owner',workspace)
        assert head is not None and resources.repository.pending_executions()==()
        with session_scope() as s:
            run=s.scalar(select(Run).where(Run.project_id=='p'))
            assert run.status==observed_status and s.get(Project,'p').active_run_id is None
        if not data['interrupt']: assert not (settings.projects_dir/'p'/'workspace'/'index.html').exists()
        listing=await orchestrator._catalog('p','owner')
        assert listing['revisionId']==head.revision_id
        if data['valid'] is None: assert listing['files']==[]
        else: assert listing['files'][0]['path']=='index.html'
        if data['interrupt']:
            from app.revision_view import materialized_revision
            registered=data['interrupt']=='deadline_checkpoint'
            with materialized_revision(resources.repository,resources.store,owner='owner',workspace_id=workspace) as view:
                assert view.path.joinpath('index.html').read_text()==('<h1>actual orchestrated output</h1>' if registered else '<h1>saved before interruption</h1>')
            with sqlite3.connect(settings.db_path) as db:
                assert db.execute('SELECT state,termination_state,outcome FROM revision_attempts').fetchall()==[('closed','confirmed','succeeded' if registered else 'cancelled')]
                assert db.execute('SELECT count(*) FROM revision_receipts').fetchone()[0]==int(registered)
                assert db.execute('SELECT count(*) FROM revision_records').fetchone()[0]==1+int(registered)
        if data['valid']: assert [entry['path'] for entry in listing['files']]==['index.html','notes.txt']
        print(json.dumps({'status':observed_status,'revision':head.revision_id}))
    finally:
        server.should_exit=True;await asyncio.wait_for(serving,15)
        broker.close();runtime.close();await broker.wait_closed();await runtime.wait_closed()
asyncio.run(main())
'''
        parameters={'code':base64.b64encode(archive.getvalue()).decode(),'admin':config.admin_token,
            'key':config.grant_key,'broker':int(broker._origin.rsplit(':',1)[1]),'runtime':relay.server_port,'valid':valid,'interrupt':interrupt}
        try:
            code,out,err=run_bounded(['docker','run','--name',name,'--network=bridge','--read-only',
                '--user','1000:1000','--cap-drop=ALL','--security-opt=no-new-privileges','--memory=512m','--pids-limit=128',
                '--tmpfs','/tmp:rw,nosuid,nodev,size=256m,mode=1777','--publish','127.0.0.1::8767',
                '--workdir','/tmp','-i',IMAGE,'/app/backend/.venv/bin/python','-I','-c',script],
                input_data=json.dumps(parameters).encode(),timeout=30)
            assert code==0,err.decode()
            assert json.loads(out)['status']==('cancelled' if interrupt=='cancel' else 'timed_out' if interrupt else 'done' if valid else 'failed')
            assert len(observed)==(2 if valid else 1)
        finally:
            relay.shutdown();relay.server_close();worker.join(timeout=3)
            run_bounded(['docker','rm','-f',name])
    assert not lifecycle.driver.owned_inventory()
