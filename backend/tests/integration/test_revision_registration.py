import base64
import asyncio
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import struct
import time
import secrets
import socket
import threading
import importlib.util
import io
import zipfile
import uuid
import subprocess
import queue
from dataclasses import replace

import pytest
import uvicorn
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, User, Project, Run
from app.revisions import Receipt, RevisionRepository
from app.artifacts import Artifact
from app.execution import ExecutionCoordinator
from app.migrations import migrate
from app.sandbox.client import BrokerClient, BrokerClientError
from app.sandbox.config import BrokerConfig
from app.sandbox.docker_driver import DockerDriver, run_bounded
from app.sandbox.grants import Grant, GrantCodec, CompletionGrantCodec
from app.sandbox.lifecycle import LifecycleError
from app.sandbox.registry import Registry, RegistryError
from app.sandbox.service import create_app

IMAGE = os.environ.get('ATOM_TEST_DOCKER_IMAGE')
pytestmark = pytest.mark.skipif(not IMAGE, reason='requires explicit pinned local Docker test image')


@contextmanager
def running_broker(path):
    config = BrokerConfig(path,IMAGE,secrets.token_urlsafe(32),secrets.token_urlsafe(32),sweep_seconds=60)
    app = create_app(config)
    listener = socket.socket()
    listener.bind(('127.0.0.1',0))
    server = uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False))
    thread = threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True)
    thread.start()
    try:
        deadline = time.monotonic()+15
        while not server.started and thread.is_alive() and time.monotonic()<deadline:
            time.sleep(0.02)
        assert server.started
        with asyncio.Runner() as runner:
            client = BrokerClient(f'http://127.0.0.1:{listener.getsockname()[1]}',config.admin_token,
                                  GrantCodec(config.grant_key.encode()))
            try:
                yield app.state.lifecycle, client, runner, config
            finally:
                runner.run(client.__aexit__())
    finally:
        server.should_exit = True
        thread.join(timeout=20)
        listener.close()
    assert not thread.is_alive()


def create_api_database(path):
    engine = create_engine('sqlite:///' + path.as_posix())
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(User(id='owner', email='owner@example.invalid', name='Owner', password_hash='fixture'))
        s.flush()
        s.add(Project(id='p',user_id='owner',title='Fixture',prompt='fixture',active_run_id='run'))
        s.flush()
        s.add(Run(id='run',project_id='p',role='alex',model='fixture',status='running'))
        s.commit()
    engine.dispose()


@pytest.mark.parametrize('state', ['unbound','bound','registered'])
def test_coordinator_cancels_actual_broker_and_releases_only_its_slot(tmp_path, state):
    root = Path(__file__).resolve().parents[3]
    path = tmp_path / 'api.db'
    create_api_database(path)
    migrate(path,tmp_path / 'backup.db')
    repo = RevisionRepository(path)
    with sqlite3.connect(path) as db:
        workspace = db.execute('SELECT id FROM revision_workspaces').fetchone()[0]
    manifest = b'{"files":[],"version":1}'
    seed = b'ATOMSNAP1\n' + struct.pack('>I',len(manifest)) + manifest
    registry = Registry(tmp_path / 'broker.db')
    driver = DockerDriver(registry.broker_id,IMAGE)
    with running_broker(registry.path) as (lifecycle, client, runner, config):
        now = int(time.time())
        ledger_grant = Grant('storage','owner','storage','storage','storage',1,
                             hashlib.sha256(manifest).hexdigest(),now,now+180)
        ledger = driver.inspect(lifecycle.provision(ledger_grant))
        sources = {name: (root / f'backend/app/{name}.py').read_text(encoding='utf-8')
                   for name in ('snapshots','artifacts')}
        script = '''
import base64,json,sys,types
from pathlib import Path
from dataclasses import asdict
data=json.loads(sys.stdin.buffer.read())
app=types.ModuleType('app');app.__path__=[];sys.modules['app']=app
for name in ('snapshots','artifacts'):
    module=types.ModuleType('app.'+name);sys.modules[module.__name__]=module;setattr(app,name,module)
    exec(compile(data['sources'][name],name+'.py','exec'),module.__dict__)
root=Path('/workspace/artifacts');root.mkdir(mode=0o700)
store=app.artifacts.ArtifactStore(root)
payload=base64.b64decode(data['seed'])
artifact=store.put(payload)
assert store.read(artifact.key)==payload
print(json.dumps(asdict(artifact)))
'''
        status, out, err = run_bounded([driver.executable,'exec','-i',ledger.id,'python3','-I','-c',script],
            input_data=json.dumps({'sources':sources,'seed':base64.b64encode(seed).decode()}).encode(),timeout=25)
        assert status == 0, err.decode()
        base = Artifact(**json.loads(out))
        repo.bootstrap('owner',workspace,base)
        intent = repo.reserve('owner',workspace,'run','attempt','target',int(time.time())+120)
        grant = Grant(intent.grant_id,'owner',intent.project_id,intent.run_id,intent.id,intent.generation,
                      intent.base_revision,intent.issued_at,intent.deadline)
        worker = None
        receipt = None
        if state != 'unbound':
            observed = runner.run(client.provision(grant))
            worker = registry.find(observed.attempt_id)
            repo.bind('owner','attempt',worker.id)
            runner.run(client.seed(grant,worker.id,seed))
            assert driver.inspect(worker).running
        if state == 'registered':
            # A real unchanged snapshot is a valid no-op revision, not generated output.
            receipt = repo.register('owner','attempt',worker.id,grant.jti,base)
        coordinator = ExecutionCoordinator(repo,client,completion_codec=CompletionGrantCodec(b'c'*32))
        async def cancel_twice():
            return await asyncio.gather(coordinator.cancel('owner','attempt'),coordinator.cancel('owner','attempt'))
        first, second = runner.run(cancel_twice())
        assert first == second == repo.recovery('owner','attempt')
        assert first.state == 'closed' and first.termination_state == 'confirmed' and first.outcome == 'cancelled'
        assert first.receipt == receipt
        if worker is not None:
            assert registry.find(worker.id).state == 'terminated' and driver.inspect(worker) is None
        else:
            assert registry.find_grant(grant.jti) is None
            with pytest.raises(BrokerClientError) as denied:
                runner.run(client.provision(grant))
            assert denied.value.status == 409
        successor = repo.reserve('owner',workspace,'run','successor','next-grant',int(time.time())+120)
        assert successor.generation == 2
        assert runner.run(coordinator.cancel('owner','attempt')) == first
        assert repo.execution('owner','successor') == successor
        assert runner.run(coordinator.cancel('owner','successor')).state == 'closed'
        assert driver.inspect(lifecycle.registry.find_grant(ledger_grant.jti)).running
    assert not driver.owned_inventory()


@pytest.mark.parametrize('cancel_before_ack,cancel_before_provision', [(False,False),(True,False),(False,True)])
def test_real_export_storage_registration_then_confirmed_release(tmp_path, cancel_before_ack, cancel_before_provision):
    root = Path(__file__).resolve().parents[3]
    path = tmp_path / 'api.db'
    create_api_database(path)
    with sqlite3.connect(path) as db:
        schema = '\n'.join(db.iterdump())
    sources = {name: (root / f'backend/app/{name}.py').read_text(encoding='utf-8')
               for name in ('snapshots','artifacts','revisions')}
    sources.update({name: (root / f'backend/app/migrations/{filename}.py').read_text(encoding='utf-8')
                    for name,filename in (('migration','__init__'),('revision_v1','revision_v1'))})
    loader = '''
import base64,json,os,sqlite3,sys,time,types
from pathlib import Path
data=json.loads(sys.stdin.buffer.read());sources=data['sources']
app=types.ModuleType('app');app.__path__=[];sys.modules['app']=app
m=types.ModuleType('app.migrations');m.__path__=[];m.__package__=m.__name__;sys.modules[m.__name__]=m
v=types.ModuleType('app.migrations.revision_v1');sys.modules[v.__name__]=v
exec(compile(sources['revision_v1'],'revision_v1.py','exec'),v.__dict__)
exec(compile(sources['migration'],'migration.py','exec'),m.__dict__)
for name in ('snapshots','artifacts','revisions'):
    module=types.ModuleType('app.'+name);sys.modules[module.__name__]=module;setattr(app,name,module)
    exec(compile(sources[name],name+'.py','exec'),module.__dict__)
path=Path('/workspace/api.db');store_path=Path('/workspace/artifacts')
'''
    registry = Registry(tmp_path / 'broker.db')
    driver = DockerDriver(registry.broker_id, IMAGE)
    manifest = b'{"files":[],"version":1}'
    seed = b'ATOMSNAP1\n' + struct.pack('>I',len(manifest)) + manifest
    now = int(time.time())
    with running_broker(registry.path) as (lifecycle, client, runner, config):
        ledger_grant = Grant('ledger-g','o','ledger-p','ledger-r','ledger-a',1,hashlib.sha256(manifest).hexdigest(),now,now+180)
        ledger = driver.inspect(lifecycle.provision(ledger_grant))
        parameters = {'sources':sources,'schema':schema,'seed':base64.b64encode(seed).decode(),
                      'grant':'g','deadline':now+180}
        def execute(body):
            status,out,err = run_bounded([driver.executable,'exec','-i',ledger.id,'python3','-I','-c',loader+body],
                                         input_data=json.dumps(parameters).encode(),timeout=25)
            assert status == 0, err.decode('utf-8')
            return out.decode().strip()
        reserved = json.loads(execute('''
from dataclasses import asdict
with sqlite3.connect(path) as db: db.executescript(data['schema'])
m.migrate(path,Path('/workspace/backup.db'))
store_path.mkdir(mode=0o700)
store=app.artifacts.ArtifactStore(store_path)
repo=app.revisions.RevisionRepository(path)
with sqlite3.connect(path) as db:
    workspace=db.execute('SELECT id FROM revision_workspaces').fetchone()[0]
base=store.put(base64.b64decode(data['seed']))
repo.bootstrap('owner',workspace,base)
pid=os.fork()
if pid==0:
    repo.reserve('owner',workspace,'run','attempt',data['grant'],data['deadline'])
    os._exit(49)
assert os.waitpid(pid,0)[1]==49<<8
attempt=repo.execution('owner','attempt')
assert attempt.broker_attempt_id is None
print(json.dumps(asdict(attempt)))
'''))
        assert registry.find_grant('g') is None
        grant = Grant(reserved['grant_id'],'owner',reserved['project_id'],reserved['run_id'],reserved['id'],
                      reserved['generation'],reserved['base_revision'],reserved['issued_at'],reserved['deadline'])
        # Linux ledger and Windows HTTP client can straddle a wall-clock second.
        # Wait for actual validity; never weaken the production grant clock check.
        clock_deadline = time.monotonic()+5
        while int(time.time()) < grant.iat and time.monotonic() < clock_deadline:
            time.sleep(0.02)
        assert grant.iat <= int(time.time()) < grant.exp
        if cancel_before_provision:
            cleanup = json.loads(execute('''
from dataclasses import asdict
repo=app.revisions.RevisionRepository(path)
pid=os.fork()
if pid==0:
    repo.cancel('owner','attempt')
    os._exit(53)
assert os.waitpid(pid,0)[1]==53<<8
recovery=app.revisions.RevisionRepository(path).recovery('owner','attempt')
assert recovery.state=='cancel_requested' and recovery.broker_attempt_id is None
assert recovery.receipt is None
print(json.dumps(asdict(recovery)))
'''))
            assert runner.run(client.revoke(cleanup['grant_id'])) == 'not_admitted'
            with pytest.raises(BrokerClientError) as denied:
                runner.run(client.provision(grant))
            assert denied.value.status == 409 and registry.find_grant(grant.jti) is None
            assert execute('''
repo=app.revisions.RevisionRepository(path)
repo.observe_termination('owner','attempt',confirmed=True,outcome='cancelled')
with sqlite3.connect(path) as db:
    assert db.execute('SELECT active_attempt_id FROM revision_workspaces').fetchone()==(None,)
    assert db.execute('SELECT broker_attempt_id,state,outcome FROM revision_attempts').fetchone()==(None,'closed','cancelled')
print('cancelled-before-creation')
''') == 'cancelled-before-creation'
            assert runner.run(client.revoke(ledger_grant.jti)) == 'terminated'
            assert not driver.owned_inventory()
            return
        provisioned = runner.run(client.provision(grant))
        worker = registry.find(provisioned.attempt_id)
        # Reconstruct the same persisted request after an unbound provision result.
        recovered = json.loads(execute('''
from dataclasses import asdict
print(json.dumps(asdict(app.revisions.RevisionRepository(path).execution('owner','attempt'))))
'''))
        assert recovered == reserved
        resumed = Grant(recovered['grant_id'],'owner',recovered['project_id'],recovered['run_id'],recovered['id'],
                        recovered['generation'],recovered['base_revision'],recovered['issued_at'],recovered['deadline'])
        assert resumed.fingerprint() == grant.fingerprint()
        assert runner.run(client.provision(resumed)) == provisioned
        parameters['worker'] = worker.id
        bound = json.loads(execute('''
from dataclasses import asdict
repo=app.revisions.RevisionRepository(path)
pid=os.fork()
if pid==0:
    repo.bind('owner','attempt',data['worker'])
    os._exit(51)
assert os.waitpid(pid,0)[1]==51<<8
attempt=repo.execution('owner','attempt')
assert repo.bind('owner','attempt',data['worker'])==attempt
print(json.dumps(asdict(attempt)))
'''))
        assert bound == {**reserved,'broker_attempt_id':worker.id}
        runner.run(client.seed(grant,worker.id,seed))
        lifecycle.file_operation(grant,worker.id,'write','tool',{'op':'write','path':'app.txt','content':'actual generated bytes\n'})
        exported = runner.run(client.export(grant,worker.id))
        parameters['output'] = base64.b64encode(exported.payload).decode()
        registered = execute('''
from dataclasses import asdict
store=app.artifacts.ArtifactStore(store_path)
repo=app.revisions.RevisionRepository(path)
output=store.put(base64.b64decode(data['output']))
pid=os.fork()
if pid==0:
    repo.register('owner','attempt',data['worker'],data['grant'],output)
    os._exit(47)
assert os.waitpid(pid,0)[1]==47<<8
receipt=repo.receipt('owner','attempt',data['worker'],data['grant'])
assert receipt is not None and store.read(receipt.artifact_key)==base64.b64decode(data['output'])
assert repo.recovery('owner','attempt').receipt==receipt
assert repo.register('owner','attempt',data['worker'],data['grant'],output)==receipt
with sqlite3.connect(path) as db:
    assert db.execute('SELECT COUNT(*) FROM revision_outbox').fetchone()==(1,)
    assert db.execute('SELECT active_attempt_id FROM revision_workspaces').fetchone()==('attempt',)
print(json.dumps(asdict(receipt)))
''')
        receipt = Receipt(**json.loads(registered))
        registered = receipt.snapshot_revision
        assert registered == exported.revision
        assert registry.find(worker.id).state == 'quiescing'
        for changed, digest in [(exported, '0'*64), (replace(exported,payload=exported.payload[:-1]),registered),
                                (replace(exported,attempt_id='other'),registered),
                                (replace(exported,attempt_version=exported.attempt_version+1),registered)]:
            with pytest.raises((LifecycleError, RegistryError)):
                lifecycle.confirm_checkpoint(grant,changed,registered_revision=digest)
            assert registry.find(worker.id).state == 'quiescing'
        if cancel_before_ack:
            cleanup = json.loads(execute('''
from dataclasses import asdict
repo=app.revisions.RevisionRepository(path)
recovery=repo.cancel('owner','attempt')
assert recovery.state=='cancel_requested' and recovery.receipt is not None
assert app.revisions.RevisionRepository(path).recovery('owner','attempt')==recovery
print(json.dumps(asdict(recovery)))
'''))
            assert cleanup['broker_attempt_id'] == worker.id
            assert runner.run(client.revoke(cleanup['grant_id'])) == 'terminated'
            with pytest.raises(BrokerClientError) as denied:
                runner.run(client.confirm(grant,exported,receipt))
            assert denied.value.status == 409
            with pytest.raises(RegistryError, match='grant_revoked'):
                lifecycle.confirm_checkpoint(grant,exported,registered_revision=registered)
            assert registry.find(worker.id).checkpoint_revision is None
        else:
            for changed in (replace(receipt,attempt_id='other'),replace(receipt,artifact_key='0'*64)):
                with pytest.raises(BrokerClientError,match='invalid_broker_request'):
                    runner.run(client.confirm(grant,exported,changed))
            confirmed = runner.run(client.confirm(grant,exported,receipt))
            assert registry.find(worker.id).state == 'checkpointed' and confirmed.revision == registered
            assert runner.run(client.confirm(grant,exported,receipt)) == confirmed
            assert driver.inspect(worker).running
        assert runner.run(client.revoke(grant.jti)) == 'terminated'
        assert registry.find(worker.id).state == 'terminated'
        assert driver.inspect(worker) is None
        outcome = 'cancelled' if cancel_before_ack else 'succeeded'
        assert execute('outcome=' + repr(outcome) + '\n' + '''
repo=app.revisions.RevisionRepository(path)
repo.observe_termination('owner','attempt',confirmed=True,outcome=outcome)
recovery=repo.recovery('owner','attempt')
assert recovery.state=='closed' and recovery.outcome==outcome and recovery.receipt is not None
assert repo.cancel('owner','attempt')==recovery
with sqlite3.connect(path) as db:
    assert db.execute('SELECT active_attempt_id FROM revision_workspaces').fetchone()==(None,)
    assert db.execute('SELECT state,termination_state,outcome FROM revision_attempts').fetchone()==('closed','confirmed',outcome)
    assert db.execute('SELECT COUNT(*) FROM revision_receipts').fetchone()==(1,)
    assert not db.execute('PRAGMA foreign_key_check').fetchall()
print('confirmed')
''') == 'confirmed'
    assert not driver.owned_inventory()


def coordinator_source_bundle():
    """Only installed pure-Python runtime dependencies, never environment files."""
    root = Path(__file__).resolve().parents[3]
    result = io.BytesIO()
    with zipfile.ZipFile(result,'w',zipfile.ZIP_DEFLATED) as bundle:
        for package in ('httpx','httpcore','anyio','certifi','idna','h11','jwt','uvicorn','click','starlette'):
            directory = Path(importlib.util.find_spec(package).origin).parent
            for path in directory.rglob('*'):
                if path.is_file() and (path.suffix == '.py' or path.name == 'cacert.pem'):
                    bundle.write(path,package+'/'+path.relative_to(directory).as_posix())
        bundle.write(importlib.util.find_spec('typing_extensions').origin,'typing_extensions.py')
        for name in ('__init__','execution','execution_http','execution_service','workspace_import','revision_view','artifacts','snapshots','revisions','migrations/__init__',
                     'migrations/revision_v1','sandbox/__init__','sandbox/client','sandbox/checkpoints',
                     'sandbox/docker_driver','sandbox/registry','sandbox/grants'):
            bundle.write(root / f'backend/app/{name}.py',f'app/{name}.py')
    return base64.b64encode(result.getvalue()).decode()


@pytest.mark.parametrize('failure', ['none','missing','cancel','registered','acknowledged','storage','decision','released','http_cancel','node','startup'])
def test_prepare_coordinator_with_real_linux_store_and_http(tmp_path, failure):
    path = tmp_path / 'api.db'
    create_api_database(path)
    with sqlite3.connect(path) as db:
        schema = '\n'.join(db.iterdump())
    name = 'atom-coordinator-test-' + uuid.uuid4().hex
    script = r"""
import asyncio,base64,io,json,sqlite3,sys,time,zipfile
from pathlib import Path
inputs=json.loads(sys.stdin.buffer.read())
code=Path('/tmp/code');code.mkdir(mode=0o700)
with zipfile.ZipFile(io.BytesIO(base64.b64decode(inputs['bundle']))) as z: z.extractall(code)
sys.path.insert(0,str(code))
from app.artifacts import ArtifactStore,ArtifactError
from app.revisions import RevisionRepository,RevisionError
from app.migrations import migrate
from app.execution import ExecutionCoordinator
from app.execution_http import ExecutionAPI
from app.workspace_import import import_workspace
from app.revision_view import materialized_revision
from app.snapshots import SnapshotError,verify_snapshot
from app.sandbox.client import BrokerClient
from app.sandbox.grants import GrantCodec,Grant,CompletionGrantCodec
import httpx,struct
async def main():
    async def relay(reader,writer):
        upstream=None
        tasks=[]
        try:
            other,upstream=await asyncio.open_connection('host.docker.internal',inputs['port'])
            async def copy(source,destination):
                while chunk:=await source.read(65536):
                    destination.write(chunk);await destination.drain()
            tasks=[asyncio.create_task(copy(reader,upstream)),asyncio.create_task(copy(other,writer))]
            await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks: task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            writer.close()
            if upstream is not None: upstream.close()
    proxy=await asyncio.start_server(relay,'127.0.0.1',0)
    origin='http://127.0.0.1:'+str(proxy.sockets[0].getsockname()[1])
    path=Path('/workspace/api.db')
    with sqlite3.connect(path) as db: db.executescript(inputs['schema'])
    migrate(path,Path('/workspace/backup.db'))
    repo=RevisionRepository(path)
    with sqlite3.connect(path) as db: workspace=db.execute('SELECT id FROM revision_workspaces').fetchone()[0]
    store_path=Path('/workspace/artifacts');store_path.mkdir(mode=0o700)
    store=ArtifactStore(store_path)
    source=Path('/workspace/legacy');source.mkdir(mode=0o700)
    (source/'initial.txt').write_text('actual imported source',encoding='utf-8')
    try: import_workspace(repo,store,owner='stranger',project_id='p',source=source)
    except RevisionError: pass
    else: raise AssertionError('foreign import')
    assert list(store_path.iterdir())==[]
    nested=store_path/'nested';nested.mkdir(mode=0o700)
    for unsafe in (Path('relative'),Path('/workspace'),store_path,nested):
        try: import_workspace(repo,store,owner='owner',project_id='p',source=unsafe)
        except RevisionError: pass
        else: raise AssertionError('unsafe source')
    nested.rmdir()
    (source/'alias').symlink_to('/etc/passwd')
    try: import_workspace(repo,store,owner='owner',project_id='p',source=source)
    except SnapshotError: pass
    else: raise AssertionError('symlink import')
    assert list(store_path.iterdir())==[]
    (source/'alias').unlink()
    imported=import_workspace(repo,store,owner='owner',project_id='p',source=source)
    assert imported.workspace_id==workspace
    assert import_workspace(repo,store,owner='owner',project_id='p',source=source)==imported
    with materialized_revision(repo,store,owner='owner',workspace_id=workspace,
                               expected_revision_id=imported.revision_id) as initial_view:
        assert initial_view.path.joinpath('initial.txt').read_text()=='actual imported source'
        assert initial_view.revision==repo.current_revision('owner',workspace)
        initial_path=initial_view.path
    assert not initial_path.exists()
    try:
        with materialized_revision(repo,store,owner='stranger',workspace_id=workspace):
            raise AssertionError('foreign view')
    except RevisionError: pass
    base=imported.artifact
    verified=verify_snapshot(io.BytesIO(store.read(base.key)))
    assert verified.revision==base.revision and len(verified.files)==1
    assert verified.files[0].path=='initial.txt'
    assert b'actual imported source' in store.read(base.key)
    (source/'initial.txt').write_text('changed source',encoding='utf-8')
    try: import_workspace(repo,store,owner='owner',project_id='p',source=source)
    except RevisionError as error: assert error.code=='revision_conflict'
    else: raise AssertionError('changed root import')
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT current_revision_id FROM revision_workspaces WHERE id=?',(workspace,)).fetchone()[0]==imported.revision_id
        assert db.execute('SELECT count(*) FROM revision_records').fetchone()[0]==1
    intent=repo.reserve('owner',workspace,'run','attempt','target',int(time.time())+120)
    # Cross-system test clock boundary; production checks remain strict.
    await asyncio.sleep(2)
    if inputs['failure']=='missing': (store_path/(base.key+'.atomsnap')).unlink()
    async with BrokerClient(origin,inputs['admin'],GrantCodec(inputs['key'].encode())) as client:
        coordinator=ExecutionCoordinator(repo,client,completion_codec=CompletionGrantCodec(b'c'*32))
        async def http_control(token, *, action='complete', body=b'', headers=None, application=None):
            import socket,uvicorn
            listener=socket.socket();listener.bind(('127.0.0.1',0));listener.setblocking(False)
            server=uvicorn.Server(uvicorn.Config(application or ExecutionAPI(coordinator,store,CompletionGrantCodec(b'c'*32)),
                lifespan='off',log_level='error',access_log=False))
            task=asyncio.create_task(server.serve(sockets=[listener]))
            try:
                until=time.monotonic()+3
                while not server.started and not task.done() and time.monotonic()<until: await asyncio.sleep(0.01)
                assert server.started
                async with httpx.AsyncClient(trust_env=False,timeout=20) as caller:
                    return await caller.post('http://127.0.0.1:'+str(listener.getsockname()[1])+'/v1/executions/'+action,
                        content=body,headers=headers if headers is not None else {'Authorization':'Bearer '+token})
            finally:
                server.should_exit=True
                await asyncio.wait_for(task,5)
                listener.close()
        try: await coordinator.prepare('stranger','attempt',store)
        except RevisionError: pass
        else: raise AssertionError('unauthorized preparation')
        if inputs['failure']=='cancel':
            import fcntl,os
            lock=os.open(store_path,os.O_RDONLY|os.O_DIRECTORY)
            fcntl.flock(lock,fcntl.LOCK_EX)
            try:
                task=asyncio.create_task(coordinator.prepare('owner','attempt',store))
                await asyncio.sleep(0.15)
                assert not task.done()
                task.cancel()
                try: await task
                except asyncio.CancelledError: pass
                else: raise AssertionError('cancelled preparation returned a lease')
            finally:
                fcntl.flock(lock,fcntl.LOCK_UN);os.close(lock)
            state=repo.recovery('owner','attempt')
            assert state.state=='closed' and state.outcome=='cancelled' and state.broker_attempt_id is None
        elif inputs['failure']=='missing':
            try: await coordinator.prepare('owner','attempt',store)
            except ArtifactError: pass
            else: raise AssertionError('missing base accepted')
            state=repo.recovery('owner','attempt')
            assert state.state=='closed' and state.outcome=='failed'
            assert state.broker_attempt_id is None
        else:
            leases=await asyncio.gather(coordinator.prepare('owner','attempt',store),
                                       coordinator.prepare('owner','attempt',store))
            lease=leases[0]
            assert leases[1]==lease and lease.grant not in repr(lease)
            assert lease.completion_grant not in repr(lease) and lease.completion_grant!=lease.grant
            completion=CompletionGrantCodec(b'c'*32).verify(lease.completion_grant)
            assert (completion.org,completion.project,completion.run,completion.attempt,completion.fence,
                    completion.jti,completion.base_revision,completion.iat,completion.exp)==(
                    'owner',intent.project_id,intent.run_id,intent.id,intent.generation,
                    intent.grant_id,intent.base_revision,intent.issued_at,intent.deadline)
            assert lease.run_id=='run' and lease.workspace_id==workspace and lease.deadline==intent.deadline
            assert repo.execution('owner','attempt').broker_attempt_id==lease.attempt_id
            if inputs['failure']=='node':
                import uvicorn
                from dataclasses import asdict
                server=uvicorn.Server(uvicorn.Config(ExecutionAPI(coordinator,store,CompletionGrantCodec(b'c'*32)),
                    host='0.0.0.0',port=8767,lifespan='off',log_level='error',access_log=False))
                serving=asyncio.create_task(server.serve())
                try:
                    until=time.monotonic()+3
                    while not server.started and not serving.done() and time.monotonic()<until: await asyncio.sleep(0.01)
                    assert server.started
                    print(json.dumps({'ready':asdict(lease)}),flush=True)
                    until=time.monotonic()+20
                    while repo.recovery('owner','attempt').state!='closed' and time.monotonic()<until:
                        await asyncio.sleep(0.05)
                    state=repo.recovery('owner','attempt')
                    assert state.state=='closed' and state.outcome=='succeeded' and state.receipt is not None
                    assert b'actual coordinator output' in store.read(state.receipt.artifact_key)
                    assert b'actual imported source' in store.read(state.receipt.artifact_key)
                finally:
                    server.should_exit=True
                    await asyncio.wait_for(serving,5)
                proxy.close();await proxy.wait_closed()
                print(json.dumps({'state':state.state,'outcome':state.outcome}))
                return
            if inputs['failure']=='none':
                from dataclasses import replace
                before=repo.recovery('owner','attempt')
                cases=[(lease.grant,403,b'',None),(inputs['admin'],403,b'',None),
                    (lease.completion_grant,400,b'{}',None),
                    (lease.completion_grant,401,b'',[(b'authorization',('Bearer '+lease.completion_grant).encode())]*2),
                    (CompletionGrantCodec(b'c'*32).issue(replace(completion,fence=completion.fence+1)),409,b'',None),
                    (CompletionGrantCodec(b'c'*32).issue(replace(completion,org='other')),403,b'',None)]
                for token,expected,body,headers in cases:
                    rejected=await http_control(token,body=body,headers=headers)
                    assert rejected.status_code==expected,rejected.text
                    assert token not in rejected.text and repo.recovery('owner','attempt')==before
            async with httpx.AsyncClient(trust_env=False) as runtime:
                denied=await runtime.get(origin+'/v1/attempts/'+lease.attempt_id,
                    headers={'Authorization':'Bearer '+lease.completion_grant})
                assert denied.status_code==403
                response=await runtime.get(origin+'/v1/attempts/'+lease.attempt_id,
                    headers={'Authorization':'Bearer '+lease.grant})
                assert response.status_code==200 and response.json()['state']=='ready'
                response=await runtime.post(origin+'/v1/attempts/'+lease.attempt_id+'/files',
                    headers={'Authorization':'Bearer '+lease.grant},json={'operation_id':'write',
                    'tool_call_id':'tool','operation':{'op':'write','path':'result.txt','content':'actual coordinator output'}})
                assert response.status_code==200
            if inputs['failure'] in ('registered','acknowledged','decision','released'):
                grant=Grant(intent.grant_id,'owner',intent.project_id,intent.run_id,intent.id,
                            intent.generation,intent.base_revision,intent.issued_at,intent.deadline)
                exported=await client.export(grant,lease.attempt_id)
                artifact=store.put(exported.payload)
                receipt=repo.register('owner','attempt',lease.attempt_id,intent.grant_id,artifact)
                if inputs['failure'] in ('acknowledged','decision','released'):
                    await client.confirm(grant,exported,receipt)
                if inputs['failure'] in ('decision','released'):
                    child = r'''
import asyncio,json,os,sys
from pathlib import Path
data=json.loads(sys.stdin.buffer.read());sys.path.insert(0,'/tmp/code')
from app.revisions import RevisionRepository
from app.sandbox.client import BrokerClient
from app.sandbox.grants import GrantCodec, CompletionGrantCodec
async def main():
    repo=RevisionRepository(Path('/workspace/api.db'))
    intent=repo.decide_termination('owner','attempt','succeeded')
    if data['release']:
        async with BrokerClient(data['origin'],data['admin'],GrantCodec(data['key'].encode())) as broker:
            assert await broker.revoke(intent.grant_id)=='terminated'
    os._exit(57)
asyncio.run(main())
'''
                    process=await asyncio.create_subprocess_exec(sys.executable,'-I','-c',child,
                        stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
                    out,err=await asyncio.wait_for(process.communicate(json.dumps({'origin':origin,
                        'admin':inputs['admin'],'key':inputs['key'],'release':inputs['failure']=='released'}).encode()),10)
                    assert process.returncode==57,err.decode()
                    pending=RevisionRepository(path).recovery('owner','attempt')
                    assert pending.state!='closed' and pending.outcome=='succeeded'
                coordinator=ExecutionCoordinator(RevisionRepository(path),client,completion_codec=CompletionGrantCodec(b'c'*32))
                if inputs['failure'] in ('decision','released'):
                    recovered=await coordinator.reconcile()
                    assert len(recovered)==1 and recovered[0].outcome=='succeeded'
                    assert await coordinator.reconcile()==()
            if inputs['failure']=='startup':
                from types import SimpleNamespace
                from app.execution_service import execution_resources,DatabaseLease,ExecutionGateway
                from app.execution import ExecutionError
                from starlette.applications import Starlette
                from starlette.routing import Route
                config=SimpleNamespace(sandbox_mode='broker',db_path=path,artifact_dir=store_path,
                    broker_origin=origin,broker_admin_token=inputs['admin'],broker_grant_key=inputs['key'],
                    completion_grant_key='c'*32)
                path.chmod(0o600)
                async def child_lease():
                    child="import sys,os;sys.path.insert(0,'/tmp/code');from app.execution_service import DatabaseLease;DatabaseLease('/workspace/api.db');os._exit(41)"
                    process=await asyncio.create_subprocess_exec(sys.executable,'-I','-c',child,
                        stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
                    await asyncio.wait_for(process.communicate(),5)
                    return process.returncode
                async with execution_resources(config) as resources:
                    state=repo.recovery('owner','attempt')
                    assert state.state=='closed' and state.outcome=='failed' and state.receipt is None
                    try: DatabaseLease(path)
                    except ExecutionError: pass
                    else: raise AssertionError('duplicate database owner')
                    assert await child_lease()!=41
                    application=Starlette(routes=[Route('/v1/executions/complete',ExecutionGateway(),methods=['POST'])])
                    application.state.execution=resources
                    rejected=await http_control('invalid',application=application)
                    assert rejected.status_code==403
                    replay=await http_control(lease.completion_grant,application=application)
                    assert replay.status_code==200 and replay.json()['outcome']=='failed'
                    repo.reserve('owner',workspace,'run','shutdown-attempt','shutdown-grant',int(time.time())+120)
                    await asyncio.sleep(2)
                    await resources.coordinator.prepare('owner','shutdown-attempt',store)
                assert resources.coordinator.broker._http.is_closed
                shutdown=repo.recovery('owner','shutdown-attempt')
                assert shutdown.state=='closed' and shutdown.termination_state=='confirmed' and shutdown.outcome=='failed'
                assert await child_lease()==41
                released=DatabaseLease(path);released.close()
                for unsafe in ('symlink','hardlink','public'):
                    alias=path.parent/'unsafe.db'
                    if unsafe=='symlink': alias.symlink_to(path)
                    elif unsafe=='hardlink': alias.hardlink_to(path)
                    else: alias=path;path.chmod(0o644)
                    try: DatabaseLease(alias)
                    except ExecutionError: pass
                    else: raise AssertionError('unsafe database accepted')
                    if alias!=path: alias.unlink()
                    path.chmod(0o600)
                original_path=config.db_path
                config.db_path=path.parent/'unmigrated.db'
                with sqlite3.connect(config.db_path) as db: db.execute('CREATE TABLE unrecognized(x)')
                config.db_path.chmod(0o600)
                try:
                    async with execution_resources(config): raise AssertionError('unmigrated database accepted')
                except RevisionError: pass
                released=DatabaseLease(config.db_path);released.close()
                config.db_path=original_path
            elif inputs['failure']=='storage':
                import fcntl,os
                lock=os.open(store_path,os.O_RDONLY|os.O_DIRECTORY);fcntl.flock(lock,fcntl.LOCK_EX)
                try:
                    failed=await http_control(lease.completion_grant)
                    assert failed.status_code==503 and failed.json()=={'error':'execution_unavailable'}
                finally:
                    fcntl.flock(lock,fcntl.LOCK_UN);os.close(lock)
                state=repo.recovery('owner','attempt')
                assert state.state=='closed' and state.outcome=='failed' and state.receipt is None
                with sqlite3.connect(path) as db:
                    assert db.execute('SELECT current_revision_id FROM revision_workspaces').fetchone()==(intent.base_revision_id,)
            elif inputs['failure']=='http_cancel':
                cancelled=await http_control(lease.completion_grant,action='cancel')
                assert cancelled.status_code==200 and cancelled.json()['outcome']=='cancelled'
                state=repo.recovery('owner','attempt')
                assert state.state=='closed' and state.receipt is None
                repeated=await http_control(lease.completion_grant,action='cancel')
                assert repeated.json()==cancelled.json()
            else:
                completed=await http_control(lease.completion_grant)
                assert completed.status_code==200,completed.text
                assert completed.headers['cache-control']=='no-store'
                state=repo.recovery('owner','attempt')
                assert completed.json()['outcome']==state.outcome and completed.json()['receipt']['revision_id']==state.receipt.revision_id
                assert state.state=='closed' and state.outcome=='succeeded' and state.receipt is not None
                assert b'actual coordinator output' in store.read(state.receipt.artifact_key)
                assert b'actual imported source' in store.read(state.receipt.artifact_key)
                try:
                    with materialized_revision(repo,store,owner='owner',workspace_id=workspace,
                                               expected_revision_id=imported.revision_id):
                        raise AssertionError('stale expected revision')
                except RevisionError as error: assert error.code=='revision_conflict'
                try:
                    with materialized_revision(repo,store,owner='owner',workspace_id=workspace,
                                               expected_revision_id=state.receipt.revision_id) as completed_view:
                        assert completed_view.path.joinpath('initial.txt').read_text()=='actual imported source'
                        assert completed_view.path.joinpath('result.txt').read_text()=='actual coordinator output'
                        completed_path=completed_view.path
                        raise RuntimeError('consumer interruption')
                except RuntimeError as error: assert str(error)=='consumer interruption'
                assert not completed_path.exists()
                repeated=await http_control(lease.completion_grant)
                assert repeated.json()==completed.json()
                with sqlite3.connect(path) as db:
                    assert db.execute('SELECT COUNT(*) FROM revision_outbox').fetchone()==(1,)
    proxy.close();await proxy.wait_closed()
    print(json.dumps({'state':state.state,'outcome':state.outcome}))
asyncio.run(main())
"""
    with running_broker(tmp_path / 'broker.db') as (lifecycle,client,runner,config):
        data={'bundle':coordinator_source_bundle(),'schema':schema,'failure':failure,
              'port':int(client._origin.rsplit(':',1)[1]),'admin':config.admin_token,'key':config.grant_key}
        try:
            command=['docker','run','--rm','--name',name,'--label',f'atom.coordinator-test={name}',
                '--network=bridge','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges',
                '--user','1000:1000','--memory=256m','--pids-limit=64',
                '--tmpfs','/tmp:rw,nosuid,nodev,size=64m,mode=1777',
                '--tmpfs','/workspace:rw,nosuid,nodev,size=64m,mode=1777',
                *(['--publish','127.0.0.1::8767'] if failure=='node' else []),
                '-i',IMAGE,'python3','-I','-c',script]
            if failure=='node':
                process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                try:
                    process.stdin.write(json.dumps(data).encode());process.stdin.close();process.stdin=None
                    ready_queue=queue.Queue()
                    reader=threading.Thread(target=lambda:ready_queue.put(process.stdout.readline()),daemon=True)
                    reader.start()
                    message=json.loads(ready_queue.get(timeout=15));reader.join(timeout=1)
                    lease=message['ready']
                    code,port,_=run_bounded(['docker','port',name,'8767/tcp'])
                    assert code==0 and port.decode().strip().startswith('127.0.0.1:')
                    runtime=Path(__file__).resolve().parents[3] / 'runtime'
                    node_input={'brokerOrigin':client._origin,'executionOrigin':'http://'+port.decode().strip(),
                        'lease':{'runId':lease['run_id'],'workspaceId':lease['workspace_id'],
                        'attemptId':lease['attempt_id'],'executionId':lease['execution_id'],'grantId':lease['grant_id'],
                        'grant':lease['grant'],'completionGrant':lease['completion_grant'],'deadline':lease['deadline']}}
                    code,node_out,node_err=run_bounded(['node','--import',(runtime/'node_modules/tsx/dist/loader.mjs').as_uri(),
                        str(runtime/'scripts/test-server-execution.ts')],input_data=json.dumps(node_input).encode(),timeout=20)
                    assert code==0,node_err.decode()
                    assert len(json.loads(node_out)['revision'])==32
                    out,err=process.communicate(timeout=10);status=process.returncode
                finally:
                    if process.poll() is None: process.kill()
                    process.communicate(timeout=5)
            else:
                status,out,err=run_bounded(command,input_data=json.dumps(data).encode(),timeout=30)
            assert status==0,err.decode()
            assert json.loads(out)['state']=='closed'
            worker=lifecycle.registry.find_grant('target')
            if failure in ('missing','cancel'): assert worker is None
            else: assert worker.state=='terminated' and lifecycle.driver.inspect(worker) is None
        finally:
            # Exact unique infrastructure name; never touch unrelated containers.
            run_bounded(['docker','rm','-f',name])
    assert not lifecycle.driver.owned_inventory()
