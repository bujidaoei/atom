"""Actual API orchestration through a host transport relay to the real Node server."""
import base64
import io
import json
import os
from pathlib import Path
import re
import subprocess
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


_OUTCOME_CASES = [(True,None),(False,None),(None,None),(False,'cancel'),(False,'deadline'),
                  (False,'deadline_checkpoint')]
_CASES = [pytest.param(version,valid,interrupt,False,False,
    id=f'schema-v{version}-{valid}-{interrupt or "normal"}')
    for version in (1,4,5,6,7,9,10,13) for valid,interrupt in _OUTCOME_CASES]
_CASES.append(pytest.param(13,True,None,True,False,id='schema-v13-configured-verifier',
    marks=pytest.mark.skipif(not os.environ.get('ATOM_VERIFIER_TEST_IMAGE_DIGEST') or
        not os.environ.get('ATOM_TEST_VERIFIER_SECCOMP_HOST_PATH'),
        reason='requires pinned Chromium and host-visible seccomp profile')))
_CASES.append(pytest.param(13,True,None,True,True,id='schema-v13-isolated-verifier',
    marks=pytest.mark.skipif(not os.environ.get('ATOM_VERIFIER_TEST_IMAGE_DIGEST') or
        not os.environ.get('ATOM_TEST_VERIFIER_SECCOMP_HOST_PATH') or
        not os.environ.get('ATOM_TEST_VERIFIER_SOURCE_HOST_PATH'),
        reason='requires pinned Chromium and host-visible source and seccomp profile')))


@pytest.mark.parametrize('schema_version,valid,interrupt,verify_output,isolate_verifier',_CASES)
def test_actual_orchestrator_leases_and_validates_registered_output(tmp_path, valid, interrupt, schema_version, verify_output, isolate_verifier):
    assert re.fullmatch(r'sha256:[0-9a-f]{64}', IMAGE)
    root=Path(__file__).resolve().parents[3]
    archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as bundle:
        for path in (root/'backend/app').rglob('*.py'):
            bundle.write(path,'app/'+path.relative_to(root/'backend/app').as_posix())
    name='atom-orchestration-test-'+uuid.uuid4().hex
    observed=[]
    sidecar_commands={}
    control_token=uuid.uuid4().hex
    # Measured Docker Desktop clock lead: retain strict production grant checks.
    with running_broker(tmp_path/'broker.db', provision_delay=1) as (lifecycle,broker,runner,config):
        class Relay(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_POST(self):
                if self.path.startswith('/verifier-control/'):
                    if self.headers.get('x-atom-test-control')!=control_token:
                        self.send_response(403);self.end_headers();return
                    command=sidecar_commands.get(self.path)
                    if command is None:
                        self.send_response(404);self.end_headers();return
                    code,out,err=run_bounded(command,timeout=25)
                    payload=out if code==0 else err
                    self.send_response(200 if code==0 else 500)
                    self.send_header('Content-Length',str(len(payload)))
                    self.end_headers();self.wfile.write(payload)
                    return
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
                    str(runtime/'scripts/test-server-execution.ts')],input_data=json.dumps(parameters).encode(),timeout=30)
                assert code==0,err.decode()
                response=json.loads(out)
                payload=''.join(json.dumps(line)+'\n' for line in response['lines']).encode()
                self.send_response(200);self.send_header('Content-Type','application/x-ndjson')
                self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        relay=ThreadingHTTPServer((os.environ.get('ATOM_TEST_BROKER_BIND_HOST','127.0.0.1'),0),Relay)
        worker=threading.Thread(target=relay.serve_forever,daemon=True);worker.start()
        script=r'''
import asyncio,base64,io,json,os,sys,zipfile,sqlite3,subprocess,time,httpx
from pathlib import Path
data=json.loads(sys.stdin.buffer.read())
code=Path('/tmp/code');code.mkdir()
with zipfile.ZipFile(io.BytesIO(base64.b64decode(data['code']))) as z:z.extractall(code)
sys.path.insert(0,str(code))
Path('/tmp/artifacts').mkdir(mode=0o700,exist_ok=True)
Path('/tmp/artifacts').chmod(0o700)
if data['isolate_verifier']:
    assert not Path('/var/run/docker.sock').exists()
os.environ.update(ATOM_ENVIRONMENT='production',ATOM_SANDBOX_MODE='broker',ATOM_COOKIE_SECURE='true',
    ATOM_SECRET='synthetic-session-key-32-characters-long',ATOM_RUNTIME_TOKEN='synthetic-runtime-key-32-characters-long',
    ATOM_DATA_DIR='/tmp/data',ATOM_DB_PATH='/tmp/data/api.db',ATOM_ARTIFACT_DIR='/tmp/artifacts',
    ATOM_BROKER_ORIGIN='http://127.0.0.1:1',ATOM_BROKER_ADMIN_TOKEN=data['admin'],ATOM_BROKER_GRANT_KEY=data['key'],
    ATOM_COMPLETION_GRANT_KEY='c'*32,ATOM_LLM_API_KEY='synthetic-model-fixture-key',
    ATOM_LLM_BASE_URL='https://synthetic.invalid/v1',ATOM_RUNTIME_URL='http://127.0.0.1:1')
if data['verify_output']:
    os.environ.update(ATOM_VERIFIER_ORIGIN='http://127.0.0.1:8799',
        ATOM_VERIFIER_CONTROL_TOKEN='synthetic-verifier-control-key-32-characters',
        ATOM_VERIFIER_POLICY_DIGEST='c'*64,ATOM_VERIFIER_RUNNER_VERSION='runner-1',
        ATOM_VERIFIER_DB_PATH='/tmp/data/api.db',ATOM_VERIFIER_ARTIFACT_DIR='/tmp/artifacts',
        ATOM_VERIFIER_IMAGE=data['verifier_image'],
        ATOM_VERIFIER_SECCOMP_PATH=data['seccomp'],ATOM_VERIFIER_ID=data['verifier_id'])
if data['isolate_verifier']:
    os.environ['ATOM_CONTENT_HOST_SUFFIX']='apps.example.net'
if data['schema_version'] in (4,5,6,7,9,10,13):
    os.environ.update(ATOM_SESSION_MODE='durable',ATOM_CONSOLE_ORIGIN='https://console.example.org',ATOM_COOKIE_SECURE='true')
from app.main import app
if data['interrupt']=='deadline_checkpoint':
    @app.middleware('http')
    async def delayed_confirmation(request,call_next):
        response=await call_next(request)
        if request.url.path=='/v1/executions/complete':await asyncio.sleep(12.5)
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
settings=get_settings()
if data['schema_version']==13:
    for version in (11,12,13):
        migrate(settings.db_path,Path(f'/tmp/data/before-v{version}.db'),target_version=version)
else:
    migrate(settings.db_path,Path('/tmp/data/backup.db'),target_version=data['schema_version'])
settings.db_path.chmod(0o600)
verifier_process=None
if data['verify_output']:
    with sqlite3.connect(settings.db_path) as db:
        db.execute('INSERT INTO requirements VALUES (?,?,?,?,?,?,?)',
                   ('page-check','p','page','Page','',
                    json.dumps([{'type':'exists','selector':'body'}]),0))
if data['schema_version'] in (4,5,6,7,9,10,13):
    from app.security import issue_session
    from app.console_auth import credentials
    console_token=issue_session('owner')
if data['interrupt']:
    legacy=settings.projects_dir/'p'/'workspace';legacy.mkdir(parents=True)
    (legacy/'index.html').write_text('<h1>saved before interruption</h1>')
async def main():
    global verifier_process
    async def start_verifier(*, restart=False):
        global verifier_process
        if data['isolate_verifier']:
            path='restart' if restart else 'start'
            async with httpx.AsyncClient(trust_env=False,timeout=30) as control:
                response=await control.post('http://host.docker.internal:'+str(data['runtime'])+
                                            '/verifier-control/'+path,
                                            headers={'x-atom-test-control':data['control_token']})
                assert response.status_code==200,response.text
        else:
            with open('/tmp/verifier.log','w') as log:
                verifier_process=subprocess.Popen([sys.executable,'-c',
                    "import sys;sys.path.insert(0,'/tmp/code');import uvicorn;from app.verifier_service import create_app;uvicorn.run(create_app(),host='127.0.0.1',port=8799,log_level='error')"],
                    env=os.environ.copy(),stdout=subprocess.DEVNULL,stderr=log)
        async with httpx.AsyncClient(base_url='http://127.0.0.1:8799',
                                     trust_env=False,timeout=2) as probe:
            deadline=time.monotonic()+20
            while True:
                if not data['isolate_verifier']:
                    assert verifier_process.poll() is None,Path('/tmp/verifier.log').read_text()
                try:
                    assert (await probe.get('/health')).json()=={'ok':True}
                    return
                except httpx.ConnectError:
                    assert time.monotonic()<deadline,(
                        'verifier_start_timeout' if data['isolate_verifier']
                        else Path('/tmp/verifier.log').read_text())
                    await asyncio.sleep(.05)
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
    if data['verify_output']:
        # A distinct main process must fail startup while its configured
        # verifier is absent, even though the real broker is ready.
        absent_env=dict(os.environ,ATOM_BROKER_ORIGIN=settings.broker_origin,
                        ATOM_RUNTIME_URL=settings.runtime_url)
        absent=await asyncio.create_subprocess_exec(sys.executable,'-c',
            "import sys;sys.path.insert(0,'/tmp/code');import uvicorn;from app.main import app;uvicorn.run(app,host='127.0.0.1',port=8768,log_level='error')",
            env=absent_env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        _unused,errors=await asyncio.wait_for(absent.communicate(),25)
        assert absent.returncode!=0 and b'verifier_unavailable' in errors,errors.decode()
        await start_verifier()
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
            await asyncio.wait_for(orchestrator._jobs['p'],40)
            with session_scope() as s:
                recorded=s.scalar(select(Run).where(Run.project_id=='p'))
                observed_status=recorded.status
                assert s.get(Project,'p').status==('ready' if expected=='done' else expected)
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
            if data['verify_output']:
                # _turn is the deterministic real-Node fixture; complete the
                # same project lifecycle transition normally owned by _build.
                await orchestrator._finish('p',status='ready')
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
            registered=True
            with materialized_revision(resources.repository,resources.store,owner='owner',workspace_id=workspace) as view:
                assert view.path.joinpath('index.html').read_text()==('<h1>actual orchestrated output</h1>' if registered else '<h1>saved before interruption</h1>')
            with sqlite3.connect(settings.db_path) as db:
                expected_ledger='cancelled' if data['interrupt']=='cancel' else 'timed_out' if data['interrupt']=='deadline' else 'succeeded'
                assert db.execute('SELECT state,termination_state,outcome FROM revision_attempts').fetchall()==[('closed','confirmed',expected_ledger)]
                assert db.execute('SELECT count(*) FROM revision_receipts').fetchone()[0]==int(registered)
                assert db.execute('SELECT count(*) FROM revision_records').fetchone()[0]==1+int(registered)
        if data['valid']: assert [entry['path'] for entry in listing['files']]==['index.html','notes.txt']
        if data['verify_output']:
            import secrets
            route='http://127.0.0.1:8767/api/projects/p/verifications'
            headers={'origin':'https://console.example.org','host':'console.example.org',
                     'x-forwarded-proto':'https'}
            async with httpx.AsyncClient(cookies={'__Host-atom_console':console_token},
                                         trust_env=False,timeout=40) as client:
                key=secrets.token_hex(16)
                reserved=await client.post(route,json={'requestId':key},headers=headers)
                assert reserved.status_code==200,reserved.text
                assert reserved.json()['revisionId']==head.revision_id
                result=await client.post(route+'/'+key+'/run',headers=headers)
                assert result.status_code==200,result.text
                assert result.json()['state']=='passed' and result.json()['total']==result.json()['passed']==1
                settled=await client.get(route+'/'+key,headers=headers)
                assert settled.status_code==200 and settled.json()==result.json()
                if data['isolate_verifier']:
                    release_route='http://127.0.0.1:8767/api/projects/p/releases'
                    release_id=secrets.token_hex(16)
                    release_command={'releaseId':release_id,'verificationId':key,
                        'expectedRevision':head.revision_id,'expectedGeneration':0,
                        'audience':'public','slug':'orchestrated-page'}
                    mutation=headers|{'x-atom-intent':'publish-verified-release'}
                    promoted=await client.post(release_route,json=release_command,headers=mutation)
                    assert promoted.status_code==200,promoted.text
                    assert promoted.json()['releaseId']==release_id
                    assert promoted.json()['revisionId']==head.revision_id
                    current=await client.get(release_route+'/current',
                        headers=headers|{'x-atom-intent':'inspect-verified-release'})
                    assert current.status_code==200,current.text
                    publication=current.json()['publication']
                    assert publication['releaseId']==release_id and publication['generation']==1
                    assert publication['pinnedUrl'].endswith('.apps.example.net/')
                    assert publication['sharingUrl']=='https://share.apps.example.net/s/orchestrated-page'
                with sqlite3.connect(settings.db_path) as db:
                    db.execute('UPDATE requirements SET checks_json=? WHERE project_id=?',
                        (json.dumps([{'type':'flow','selector':'#missing','expect':'body'}]),'p'))
                interrupted_key=secrets.token_hex(16)
                new_request=await client.post(route,json={'requestId':interrupted_key},headers=headers)
                assert new_request.status_code==200,new_request.text
                running=asyncio.create_task(client.post(route+'/'+interrupted_key+'/run',headers=headers))
                deadline=time.monotonic()+15
                while True:
                    if data['isolate_verifier']:
                        async with httpx.AsyncClient(trust_env=False,timeout=5) as control:
                            inventory=await control.post('http://host.docker.internal:'+str(data['runtime'])+
                                                         '/verifier-control/worker',
                                                         headers={'x-atom-test-control':data['control_token']})
                        assert inventory.status_code==200,inventory.text
                        observed_worker=inventory.content.strip()
                    else:
                        inventory=await asyncio.to_thread(subprocess.run,
                            ['docker','ps','-q','--filter','label=atom.verifier.owner='+data['verifier_id']],
                            capture_output=True,check=True,timeout=3)
                        observed_worker=inventory.stdout.strip()
                    if observed_worker:break
                    assert not running.done() and time.monotonic()<deadline
                    await asyncio.sleep(.05)
                if data['isolate_verifier']:
                    async with httpx.AsyncClient(trust_env=False,timeout=30) as control:
                        stopped=await control.post('http://host.docker.internal:'+str(data['runtime'])+
                                                   '/verifier-control/kill',
                                                   headers={'x-atom-test-control':data['control_token']})
                        assert stopped.status_code==200,stopped.text
                else:
                    verifier_process.kill()
                    await asyncio.to_thread(verifier_process.wait,10)
                unknown=await running
                assert unknown.status_code==202 and unknown.json()['state'] in ('running','unresolved'),unknown.text
                await start_verifier(restart=True)
                after=await client.get(route+'/'+interrupted_key,headers=headers)
                assert after.status_code==200 and after.json()==unknown.json()
                no_replay=await client.post(route+'/'+interrupted_key+'/run',headers=headers)
                assert no_replay.status_code==202 and no_replay.json()==after.json()
                if data['isolate_verifier']:
                    async with httpx.AsyncClient(trust_env=False,timeout=5) as control:
                        inventory=await control.post('http://host.docker.internal:'+str(data['runtime'])+
                                                     '/verifier-control/inventory',
                                                     headers={'x-atom-test-control':data['control_token']})
                    assert inventory.status_code==200 and not inventory.content.strip()
                else:
                    inventory=await asyncio.to_thread(subprocess.run,
                        ['docker','ps','-aq','--filter','label=atom.verifier.owner='+data['verifier_id']],
                        capture_output=True,check=True,timeout=3)
                    assert not inventory.stdout.strip()
            with sqlite3.connect(settings.db_path) as db:
                assert db.execute('SELECT outcome FROM verification_results WHERE request_id=?',(key,)).fetchone()==('passed',)
                assert db.execute('SELECT count(*) FROM verification_attestations').fetchone()==(1,)
                assert db.execute('SELECT count(*) FROM verification_dispatches').fetchone()==(2,)
                assert db.execute('SELECT count(*) FROM verification_results').fetchone()==(1,)
                if data['isolate_verifier']:
                    assert db.execute('SELECT count(*) FROM release_records').fetchone()==(1,)
                    assert db.execute('SELECT count(*) FROM content_bindings').fetchone()==(1,)
        if data['schema_version'] in (4,5,6,7,9,10,13):
            codec=credentials();source=codec.authenticate(console_token)
            assert source and source.user_id=='owner'
            codec.repository.revoke_console_session(user_id='owner',session_id=source.id)
            assert codec.authenticate(console_token) is None
            if data['schema_version'] in (5,6,7,9,10,13):
                with sqlite3.connect(settings.db_path) as db:
                    events=[row[0] for row in db.execute('SELECT event_kind FROM security_audit_events ORDER BY sequence')]
                    assert events[0]=='console.session.created' and events[-1]=='console.session.revoked'
                    if not data['verify_output']: assert len(events)==2
        print(json.dumps({'status':observed_status,'revision':head.revision_id}))
    finally:
        server.should_exit=True;await asyncio.wait_for(serving,15)
        broker.close();runtime.close();await broker.wait_closed();await runtime.wait_closed()
        assert app.state.verifier_client is None
try:asyncio.run(main())
finally:
    if verifier_process is not None:
        verifier_process.terminate()
        try:verifier_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            verifier_process.kill();verifier_process.wait(timeout=5)
'''
        parameters={'code':base64.b64encode(archive.getvalue()).decode(),'admin':config.admin_token,
            'key':config.grant_key,'broker':int(broker._origin.rsplit(':',1)[1]),'runtime':relay.server_port,
            'valid':valid,'interrupt':interrupt,'schema_version':schema_version,
            'verify_output':verify_output,'isolate_verifier':isolate_verifier,
            'control_token':control_token}
        extra=[]
        test_volumes=[]
        created_volumes=[]
        sidecar_name=name+'-verifier'
        if verify_output:
            seccomp=Path(os.environ['ATOM_TEST_VERIFIER_SECCOMP_HOST_PATH'])
            assert seccomp.is_absolute() and seccomp.is_file()
            verifier_image=os.environ['ATOM_VERIFIER_TEST_IMAGE_DIGEST']
            assert re.fullmatch(r'sha256:[0-9a-f]{64}',verifier_image)
            parameters.update(verifier_image=verifier_image,seccomp=str(seccomp),
                              verifier_id='orchestrated-'+uuid.uuid4().hex)
            if isolate_verifier:
                source=Path(os.environ['ATOM_TEST_VERIFIER_SOURCE_HOST_PATH'])
                assert source.is_absolute() and (source/'backend/app/verifier_service.py').is_file()
                test_volumes=[name+'-data',name+'-artifacts']
                extra=['--user','0:0','--mount',f'type=volume,source={test_volumes[0]},target=/tmp/data',
                       '--mount',f'type=volume,source={test_volumes[1]},target=/tmp/artifacts']
                sidecar_commands.update({
                    '/verifier-control/start':['docker','run','-d','--name',sidecar_name,
                        '--network','container:'+name,'--volumes-from',name,
                        '--volume','/var/run/docker.sock:/var/run/docker.sock',
                        '--volume','/usr/bin/docker:/usr/bin/docker:ro',
                        '--volume',f'{seccomp}:{seccomp}:ro',
                        '--volume',f'{source}:{source}:ro',
                        '--user','0:0','--cap-drop','ALL','--security-opt','no-new-privileges',
                        '--workdir',str(source/'backend'),
                        '-e','PYTHONPATH='+str(source/'backend'),
                        '-e','ATOM_VERIFIER_DB_PATH=/tmp/data/api.db',
                        '-e','ATOM_VERIFIER_ARTIFACT_DIR=/tmp/artifacts',
                        '-e','ATOM_VERIFIER_IMAGE='+verifier_image,
                        '-e','ATOM_VERIFIER_SECCOMP_PATH='+str(seccomp),
                        '-e','ATOM_VERIFIER_ID='+parameters['verifier_id'],
                        '-e','ATOM_VERIFIER_CONTROL_TOKEN=synthetic-verifier-control-key-32-characters',
                        IMAGE,'/app/backend/.venv/bin/python','-m','uvicorn',
                        'app.verifier_service:create_app','--factory','--app-dir',str(source/'backend'),
                        '--host','127.0.0.1',
                        '--port','8799','--log-level','error'],
                    '/verifier-control/kill':['docker','kill',sidecar_name],
                    '/verifier-control/restart':['docker','start',sidecar_name],
                    '/verifier-control/worker':['docker','ps','-q','--filter',
                        'label=atom.verifier.owner='+parameters['verifier_id']],
                    '/verifier-control/inventory':['docker','ps','-aq','--filter',
                        'label=atom.verifier.owner='+parameters['verifier_id']]})
            else:
                # Earlier service-behavior harness; the new isolated case keeps
                # the API's daemon socket absent throughout the same workflow.
                extra=['--user','0:0','--volume','/var/run/docker.sock:/var/run/docker.sock',
                       '--volume','/usr/bin/docker:/usr/bin/docker:ro',
                       '--volume',f'{seccomp}:{seccomp}:ro']
        try:
            for volume in test_volumes:
                code,out,err=run_bounded(['docker','volume','create','--label',
                    'atom.test.owner='+name,volume])
                assert code==0,err.decode()
                created_volumes.append(volume)
            process=subprocess.run(['docker','run','--name',name,'--network=bridge',
                '--add-host','host.docker.internal:host-gateway','--read-only',
                *([] if verify_output else ['--user','1000:1000']),
                '--cap-drop=ALL','--security-opt=no-new-privileges','--memory=512m','--pids-limit=128',
                '--tmpfs','/tmp:rw,nosuid,nodev,size=256m,mode=1777','--publish','127.0.0.1::8767',
                *extra,'--workdir','/tmp','-i',IMAGE,'/app/backend/.venv/bin/python','-I','-c',script],
                input=json.dumps(parameters).encode(),capture_output=True,
                timeout=180 if verify_output else 55,check=False)
            assert len(process.stdout)+len(process.stderr)<=256*1024
            if process.returncode!=0 and isolate_verifier:
                code,logs,err=run_bounded(['docker','logs',sidecar_name],output_limit=8192)
                assert process.returncode==0,process.stderr.decode()+'\nverifier logs: '+(
                    logs+err).decode(errors='replace')
            assert process.returncode==0,process.stderr.decode()
            assert json.loads(process.stdout)['status']==('cancelled' if interrupt=='cancel' else 'timed_out' if interrupt else 'done' if valid else 'failed')
            assert len(observed)==(2 if valid else 1)
        finally:
            relay.shutdown();relay.server_close();worker.join(timeout=3)
            if isolate_verifier:
                run_bounded(['docker','rm','-f',sidecar_name])
            run_bounded(['docker','rm','-f',name])
            for volume in created_volumes:
                code,out,err=run_bounded(['docker','volume','rm',volume])
                assert code==0,err.decode()
            if verify_output:
                code,out,err=run_bounded(['docker','ps','-aq','--filter',
                    'label=atom.verifier.owner='+parameters['verifier_id']])
                assert code==0 and not out.strip(),err.decode()
    assert not lifecycle.driver.owned_inventory()
