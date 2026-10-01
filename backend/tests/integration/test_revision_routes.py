"""Actual FastAPI routes and Linux artifact IO in an explicitly selected API image."""
import base64
import io
import json
import os
import re
from pathlib import Path
import uuid
import zipfile

import pytest

from app.sandbox.docker_driver import run_bounded

IMAGE = os.environ.get('ATOM_TEST_API_IMAGE')
pytestmark = pytest.mark.skipif(not IMAGE, reason='requires an explicit local API image digest')


def test_committed_preview_and_file_routes_on_linux():
    assert re.fullmatch(r'sha256:[0-9a-f]{64}', IMAGE)
    root = Path(__file__).resolve().parents[3]
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for path in (root/'backend/app').rglob('*.py'):
            bundle.write(path, 'app/'+path.relative_to(root/'backend/app').as_posix())
    script = r'''
import asyncio,base64,io,json,os,sys,zipfile
from pathlib import Path
from types import SimpleNamespace
code=Path('/tmp/code');code.mkdir()
with zipfile.ZipFile(io.BytesIO(base64.b64decode(source['code']))) as z: z.extractall(code)
sys.path.insert(0,str(code))
os.environ.update(ATOM_ENVIRONMENT='test',ATOM_SANDBOX_MODE='local',
    ATOM_SECRET='synthetic-session-key-32-characters-long',
    ATOM_RUNTIME_TOKEN='synthetic-runtime-key-32-characters-long',
    ATOM_DATA_DIR='/tmp/data',ATOM_DB_PATH='/tmp/data/api.db',ATOM_LLM_API_KEY='',
    ATOM_RUNTIME_URL='http://127.0.0.1:1')
from app.main import app
from app.config import get_settings
from app.db import engine,session_scope
from app.models import Base,User,Project,Race,RaceHeat
from app.migrations import migrate
from app.revisions import RevisionRepository
from app.artifacts import ArtifactStore
from app.workspace_import import import_workspace
from app.security import issue_session
import httpx
Base.metadata.create_all(engine)
with session_scope() as s:
    s.add_all([User(id='owner',email='owner@example.invalid',name='Owner',password_hash='fixture'),
               User(id='other',email='other@example.invalid',name='Other',password_hash='fixture')]);s.flush()
    s.add_all([Project(id='p',user_id='owner',title='P',prompt='fixture',slug='published'),
               Project(id='empty',user_id='owner',title='Empty',prompt='fixture'),
               Project(id='q',user_id='owner',title='Q',prompt='fixture')]);s.flush()
    s.add_all([Race(id='race',project_id='p'),Race(id='foreign-race',project_id='q')]);s.flush()
    s.add_all([RaceHeat(id='heat',race_id='race',model='fixture',status='done',file_count=999,bytes=999),
               RaceHeat(id='foreign',race_id='foreign-race',model='fixture')])
settings=get_settings()
migrate(settings.db_path,Path('/tmp/data/backup.db'))
repo=RevisionRepository(settings.db_path)
store_root=Path('/tmp/artifacts');store_root.mkdir(mode=0o700)
store=ArtifactStore(store_root)
legacy=settings.projects_dir/'p'/'workspace';legacy.mkdir(parents=True)
(legacy/'index.html').write_text('<h1>committed</h1>')
(legacy/'style.css').write_text('body { color: blue; }')
main=import_workspace(repo,store,owner='owner',project_id='p',source=legacy)
original_payload=store.read(main.artifact.key)
branch=Path('/tmp/branch');branch.mkdir();(branch/'index.html').write_text('<h1>branch</h1>')
heat=import_workspace(repo,store,owner='owner',project_id='p',heat_id='heat',source=branch)
from app import storage
legacy_heat=storage.workspace_dir('p','heat');legacy_heat.mkdir(parents=True)
(legacy_heat/'index.html').write_text('<h1>stale heat directory</h1>')
(legacy/'index.html').write_text('<h1>uncommitted stale legacy</h1>')
(legacy/'legacy-only.txt').write_text('not committed')
with session_scope() as s:
    s.get(Project,'p').status='ready'
settings.sandbox_mode='broker'
# Actual routes/dependencies/auth/database/storage; lifespan is separately tested.
app.state.execution=SimpleNamespace(repository=repo,store=store)
async def main_test():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        for cookie in (None,issue_session('other')):
            headers={} if cookie is None else {'Cookie':'atom_session='+cookie}
            assert (await client.get('/preview/p/',headers=headers)).status_code==404
        headers={'Cookie':'atom_session='+issue_session('owner')}
        detail=await client.get('/api/projects/p',headers=headers)
        assert detail.status_code==200,detail.text
        project=detail.json()['project']
        assert project['legacyPublicationAvailable'] is False
        assert project['legacyAdoptionAvailable'] is False
        denied=await client.post('/api/projects/p/publish',headers=headers)
        assert denied.status_code==409
        denied_adoption=await client.post('/api/projects/p/race/heat/adopt',headers=headers)
        assert denied_adoption.status_code==409
        assert '旧目录复制' in denied_adoption.json()['detail']
        with session_scope() as s:
            assert s.get(Race,'race').winner_heat_id is None
            assert s.get(Project,'p').status=='ready'
        assert (legacy/'index.html').read_text()=='<h1>uncommitted stale legacy</h1>'
        assert repo.current_revision('owner',main.workspace_id).revision_id==main.revision_id
        assert not (settings.published_dir/'published').exists()
        assert project['revisionId']==main.revision_id
        assert [item['path'] for item in project['files']]==['index.html','style.css']
        assert all(item['timestampSource']=='revision' and len(item['sha256'])==64 for item in project['files'])
        assert project['files'][0]['bytes']==len('<h1>committed</h1>')
        assert (await client.get('/api/projects/p',headers=headers)).json()['project']['files']==project['files']
        assert not list(Path('/tmp').glob('atom-revision-*'))
        race=(await client.get('/api/projects/p/race',headers=headers)).json()['race']
        assert race==project['race']
        assert race['heats'][0]['fileCount']==1 and race['heats'][0]['bytes']==len('<h1>branch</h1>')
        assert race['heats'][0]['revisionId']==heat.revision_id
        assert race['heats'][0]['previewUrl']=='/preview/p/race/heat/'
        empty=(await client.get('/api/projects/empty',headers=headers)).json()['project']
        assert empty['revisionId'] is None and empty['files']==[]
        created=await client.post('/api/projects',headers=headers,json={'prompt':'Create a real dashboard'})
        assert created.status_code==201,created.text
        assert created.json()['project']['revisionId'] is None and created.json()['project']['files']==[]
        for url,content,revision in [('/preview/p/','<h1>committed</h1>',main.revision_id),
                                    ('/preview/p/spa/path','<h1>committed</h1>',main.revision_id),
                                    ('/api/projects/p/files/index.html','<h1>committed</h1>',main.revision_id),
                                    ('/preview/p/race/heat/','<h1>branch</h1>',heat.revision_id)]:
            response=await client.get(url,headers=headers)
            assert response.status_code==200,(url,response.text)
            assert response.text==content and response.headers['x-atom-revision']==revision
            assert response.headers['cache-control']=='no-store'
            assert not list(Path('/tmp').glob('atom-revision-*'))
        assert (await client.get('/preview/p/style.css',headers=headers)).text=='body { color: blue; }'
        for url in ('/preview/p/race/foreign/','/preview/empty/','/api/projects/empty/files/index.html'):
            assert (await client.get(url,headers=headers)).status_code==404
        assert (await client.get('/preview/p/%2e%2e%2fsecret',headers=headers)).status_code==403
        assert (await client.get('/api/projects/p/files/%2e%2e%2fsecret',headers=headers)).status_code==404
        assert not list(Path('/tmp').glob('atom-revision-*'))
        from app.revision_http import _READS
        _READS.acquire()
        try:
            assert (await client.get('/preview/p/',headers=headers)).status_code==503
        finally:
            _READS.release()
        target=store_root/(main.artifact.key+'.atomsnap');target.write_bytes(b'corrupt')
        failed=await client.get('/preview/p/',headers=headers)
        assert failed.status_code==503 and 'corrupt' not in failed.text
        assert (await client.get('/api/projects/p',headers=headers)).status_code==503
        assert not list(Path('/tmp').glob('atom-revision-*'))
        app.state.execution=None
        assert (await client.get('/preview/p/',headers=headers)).status_code==503
asyncio.run(main_test())
target=store_root/(main.artifact.key+'.atomsnap');target.write_bytes(original_payload)
migrate(settings.db_path,Path('/tmp/data/before-release.db'),target_version=2)
from app.models import Requirement
from app.verification_contract import capture_contract
from app.verification_repository import VerificationRepository,VerificationError
from app.release_repository import ReleaseRepository
from app.release_view import materialized_release
from app.artifacts import ArtifactError
requirement={'key':'page','title':'Page','detail':'','checks':[{'type':'exists','selector':'h1'}]}
with session_scope() as s:
    s.add(Requirement(project_id='p',key='page',title='Page',detail='',checks_json=json.dumps(requirement['checks'])))
verification=VerificationRepository(settings.db_path)
request=verification.reserve(owner='owner',workspace_id=main.workspace_id,request_id='check',
    expected_revision=main.revision_id,expected_contract=capture_contract([requirement]).digest,
    policy_digest='c'*64,runner_version='fixture-runner',budget_seconds=60)
# Fixture report only; this test verifies actual stored artifacts, not a browser verifier.
verification.record_report(owner='owner',request_id=request.id,results=[{'key':'page','checkIndex':0,'passed':True,'note':'fixture'}])
releases=ReleaseRepository(settings.db_path)
releases.publish(owner='owner',project_id='p',release_id='published-release',verification_id=request.id,
    expected_revision=main.revision_id,expected_generation=0,policy_digest='c'*64,runner_version='fixture-runner',audience='public',slug='site')
from concurrent.futures import ThreadPoolExecutor
def competing_view():
    try:
        with materialized_release(releases,store,slug='site'):raise AssertionError('capacity bypass')
    except VerificationError as error:return str(error)
with materialized_release(releases,store,slug='site'):
    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(competing_view).result(timeout=5)=='release_capacity'
for exceptional in (False,True):
    try:
        with materialized_release(releases,store,slug='site') as view:
            saved_path=view.path
            assert (view.path/'index.html').read_text()=='<h1>committed</h1>'
            assert not (view.path/'legacy-only.txt').exists()
            assert view.publication.revision_id==main.revision_id
            if exceptional:raise RuntimeError('consumer failure')
    except RuntimeError:
        assert exceptional
    assert not saved_path.exists() and not list(Path('/tmp').glob('atom-release-*'))
target.write_bytes(b'corrupt')
try:
    with materialized_release(releases,store,slug='site'):raise AssertionError('corrupt artifact admitted')
except ArtifactError:pass
target.write_bytes(original_payload)
read=store.read
def revoke_during_read(key):
    payload=read(key)
    releases.unpublish(owner='owner',project_id='p',command_id='off',expected_release='published-release',expected_generation=1)
    return payload
store.read=revoke_during_read
try:
    with materialized_release(releases,store,slug='site'):raise AssertionError('revoked artifact admitted')
except VerificationError as error:assert str(error)=='release_not_found'
assert not list(Path('/tmp').glob('atom-release-*'))
store.read=read
releases.publish(owner='owner',project_id='p',release_id='replacement',verification_id=request.id,
    expected_revision=main.revision_id,expected_generation=2,policy_digest='c'*64,runner_version='fixture-runner',audience='public',slug='site')
import app.release_view as release_view
receive=release_view.receive_snapshot
def revoke_during_extraction(stream,path):
    received=receive(stream,path)
    assert (received.path/'index.html').is_file()
    releases.unpublish(owner='owner',project_id='p',command_id='off-after-extraction',expected_release='replacement',expected_generation=3)
    return received
release_view.receive_snapshot=revoke_during_extraction
try:
    with materialized_release(releases,store,slug='site'):raise AssertionError('extracted revoked artifact admitted')
except VerificationError as error:assert str(error)=='release_not_found'
assert not list(Path('/tmp').glob('atom-release-*'))
assert release_view._READS.acquire(blocking=False)
release_view._READS.release()
release_view.receive_snapshot=receive
migrate(settings.db_path,Path('/tmp/data/before-content.db'),target_version=3)
from app.content_repository import ContentRepository
from app.content_hosts import ContentHosts
from app.content_service import ContentService,ContentLimits
releases.publish(owner='owner',project_id='p',release_id='http-release',verification_id=request.id,
    expected_revision=main.revision_id,expected_generation=4,policy_digest='c'*64,runner_version='fixture-runner',audience='public',slug='site')
content=ContentRepository(settings.db_path)
binding=content.bind(owner='owner',project_id='p',release_id='http-release')
hosts=ContentHosts('content.example.test')
service=ContentService(content,store,hosts)
async def content_test():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=service),base_url=hosts.url(binding.id)) as client:
        page=await client.get('/')
        assert page.status_code==200 and page.text=='<h1>committed</h1>'
        shared=await client.get(hosts.sharing_url('site')+'?next=https://attacker.invalid/')
        assert shared.status_code==307 and shared.headers['location']==hosts.url(binding.id)
        assert shared.headers['cache-control']=='no-store' and not shared.content
        assert (await client.head(hosts.sharing_url('site'))).headers['location']==hosts.url(binding.id)
        assert (await client.get(hosts.sharing_url('missing'))).status_code==404
        assert (await client.get(hosts.sharing_url('site')+'/extra')).status_code==404
        assert (await client.post(hosts.sharing_url('site'))).status_code==405
        assert page.headers['x-atom-release']=='http-release'
        assert page.headers['x-atom-revision']==main.revision_id
        assert page.headers['cache-control']=='no-store'
        assert page.headers['x-content-type-options']=='nosniff'
        assert "worker-src 'none'" in page.headers['content-security-policy']
        limited=ContentService(content,store,hosts,limits=ContentLimits(active_responses=1,send_seconds=0.1))
        scope={'type':'http','method':'GET','path':'/',
            'headers':[(b'host',hosts.hostname(binding.id).encode())]}
        async def receive_http():return {'type':'http.request','body':b'','more_body':False}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=limited),base_url=hosts.url(binding.id)) as bounded:
            # Hold real response bytes at ASGI delivery, then timeout/cancel/error.
            for outcome in ('timeout','cancel','error'):
                started=asyncio.Event();unblock=asyncio.Event();sent=[]
                async def slow_send(message):
                    sent.append(message['type'])
                    if message['type']=='http.response.body':
                        started.set()
                        await unblock.wait()
                        raise OSError('fixture disconnected transport')
                pending=asyncio.create_task(limited(scope,receive_http,slow_send))
                await asyncio.wait_for(started.wait(),2)
                assert (await bounded.get('/')).status_code==503
                if outcome=='cancel':pending.cancel()
                if outcome=='error':unblock.set()
                done,_=await asyncio.wait({pending},timeout=1)
                assert pending in done,'service failed to bound delivery independently of test timeout'
                try:
                    await pending
                    raise AssertionError('delivery failure not propagated')
                except (TimeoutError,asyncio.CancelledError,OSError) as error:
                    expected={'timeout':TimeoutError,'cancel':asyncio.CancelledError,'error':OSError}[outcome]
                    assert isinstance(error,expected)
                assert sent==['http.response.start','http.response.body']
                assert (await bounded.get('/')).status_code==200
            # Cancellation cannot release a slot while actual synchronous IO runs.
            from threading import Event
            entered=Event();finish=Event();read_calls=[]
            real_read=store.read
            def held_read(key):
                read_calls.append(key);entered.set()
                assert finish.wait(2),'fixture release not signalled'
                return real_read(key)
            store.read=held_read
            try:
                pending=asyncio.create_task(bounded.get('/'))
                assert await asyncio.to_thread(entered.wait,2)
                owned=tuple(limited._reads)
                assert len(owned)==1
                pending.cancel()
                try:
                    await pending
                    raise AssertionError('request cancellation swallowed')
                except asyncio.CancelledError:pass
                assert not owned[0].done()
                assert (await bounded.get('/')).status_code==503
                assert len(read_calls)==1
            finally:
                finish.set()
                store.read=real_read
            await asyncio.wait_for(asyncio.gather(*owned),2)
            await asyncio.sleep(0) # Run completion callbacks that release ownership.
            assert not limited._reads
            assert (await bounded.get('/')).status_code==200
            assert not list(Path('/tmp').glob('atom-release-*'))
        for expire in (False,True):
            draining=ContentService(content,store,hosts,
                limits=ContentLimits(active_responses=2,drain_seconds=0.05 if expire else 2))
            entered=Event();finish=Event();shutdown_seen=asyncio.Event()
            events=asyncio.Queue();messages=[]
            async def life_receive():
                message=await events.get()
                if message['type']=='lifespan.shutdown':shutdown_seen.set()
                return message
            async def life_send(message):messages.append(message)
            life=asyncio.create_task(draining({'type':'lifespan'},life_receive,life_send))
            await events.put({'type':'lifespan.startup'})
            real_read=store.read
            def drain_read(key):
                entered.set()
                assert finish.wait(3),'fixture drain release not signalled'
                return real_read(key)
            store.read=drain_read
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=draining),base_url=hosts.url(binding.id)) as drain_client:
                try:
                    pending=asyncio.create_task(drain_client.get('/'))
                    assert await asyncio.to_thread(entered.wait,2)
                    owned=tuple(draining._reads)
                    pending.cancel()
                    try:await pending
                    except asyncio.CancelledError:pass
                    await events.put({'type':'lifespan.shutdown'})
                    await asyncio.wait_for(shutdown_seen.wait(),1)
                    assert draining._draining and not life.done()
                    # A second capacity slot exists but shutdown forbids new IO.
                    assert (await drain_client.get('/')).status_code==503
                    if expire:
                        done,_=await asyncio.wait({life},timeout=1)
                        assert life in done
                        assert messages[-1]=={'type':'lifespan.shutdown.failed','message':'content_drain_timeout'}
                        assert draining._pending and all(not token.done() for token in draining._pending)
                finally:
                    finish.set();store.read=real_read
                await asyncio.wait_for(asyncio.gather(*owned),2)
                await asyncio.wait_for(life,2)
                assert messages[0]=={'type':'lifespan.startup.complete'}
                assert messages[-1]['type']==('lifespan.shutdown.failed' if expire else 'lifespan.shutdown.complete')
                assert not draining._pending and not draining._reads
                assert (await drain_client.get('/')).status_code==503
        # Actual TCP HTTP parser/listener and ASGI lifespan, inside Linux.
        import socket,uvicorn
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(16)
        port=listener.getsockname()[1]
        network_service=ContentService(content,store,hosts)
        server=uvicorn.Server(uvicorn.Config(network_service,log_level='critical',access_log=False,
            lifespan='on',proxy_headers=False,timeout_graceful_shutdown=2))
        serving=asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(2):
                while not server.started:
                    if serving.done():await serving;raise AssertionError('server stopped before startup')
                    await asyncio.sleep(0.01)
            async with httpx.AsyncClient(base_url='http://127.0.0.1:'+str(port),trust_env=False,timeout=2) as network:
                valid={'host':hosts.hostname(binding.id)}
                real_page=await network.get('/',headers=valid)
                assert real_page.status_code==200 and real_page.content==page.content
                assert (await network.head('/',headers=valid)).headers['content-length']==page.headers['content-length']
                assert (await network.get('/style.css',headers=valid)).text=='body { color: blue; }'
                redirect=await network.get('/s/site',headers={'host':'share.'+hosts.suffix})
                assert redirect.status_code==307 and redirect.headers['location']==hosts.url(binding.id)
                assert redirect.headers['cache-control']=='no-store'
                assert (await network.get('/')).status_code==404
                assert (await network.get('/',headers={'x-forwarded-host':hosts.hostname(binding.id)})).status_code==404
        finally:
            server.should_exit=True
            await asyncio.wait_for(serving,4)
            listener.close()
        assert network_service._draining and not network_service._pending
        head=await client.head('/')
        assert head.status_code==200 and head.content==b''
        assert head.headers['content-length']==page.headers['content-length']
        css=await client.get('/style.css')
        assert css.status_code==200 and 'blue' in css.text
        assert css.headers['content-type'].startswith('text/css')
        assert (await client.get('/route',headers={'sec-fetch-mode':'navigate'})).text==page.text
        for path in ('/route','/missing.css','/legacy-only.txt','/%2e%2e/secret','/bad%5cpath'):
            assert (await client.get(path)).status_code==404,path
        assert (await client.get('/missing.css',headers={'sec-fetch-mode':'navigate'})).status_code==404
        assert (await client.post('/')).status_code==405
        assert (await client.get('/',headers={'host':'console.example.test'})).status_code==404
        assert (await client.get('/',headers={'host':'console.example.test','x-forwarded-host':hosts.hostname(binding.id)})).status_code==404
        target.write_bytes(b'corrupt')
        failed=await client.get('/')
        assert failed.status_code==503 and not failed.content
        target.write_bytes(original_payload)
        # Separate real artifact bytes, with an explicitly seeded ledger history.
        # This is serving/promotion coverage, not execution-provenance acceptance.
        import sqlite3,time
        from app.models import Run
        from app.snapshots import export_snapshot
        changed=Path('/tmp/changed');changed.mkdir()
        (changed/'index.html').write_text('<link rel="stylesheet" href="/style.css"><h1>second</h1>')
        (changed/'style.css').write_text('body { color: red; }')
        stream=io.BytesIO();export_snapshot(changed,stream)
        artifact=store.put(stream.getvalue())
        with session_scope() as s:
            s.add(Run(id='fixture-change',project_id='p',role='engineer',model='fixture',status='succeeded'))
        now=int(time.time())
        with sqlite3.connect(settings.db_path) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('INSERT INTO revision_artifacts VALUES (?,?,?,?)',(artifact.key,artifact.revision,artifact.size,now))
            db.execute("""INSERT INTO revision_attempts
                (id,workspace_id,project_id,run_id,generation,base_revision_id,deadline,state,termination_state,outcome,created_at,closed_at)
                VALUES (?,?,?,'fixture-change',1,?,?,'closed','confirmed','succeeded',?,?)""",
                ('fixture-change',main.workspace_id,'p',main.revision_id,now+60,now,now))
            db.execute('INSERT INTO revision_records VALUES (?,?,?,?,?,?,?,?)',
                ('second-revision',main.workspace_id,'p',main.revision_id,artifact.key,artifact.revision,'fixture-change',now))
            db.execute('UPDATE revision_workspaces SET current_revision_id=?,generation=1 WHERE id=?',('second-revision',main.workspace_id))
        second_check=verification.reserve(owner='owner',workspace_id=main.workspace_id,request_id='second-check',
            expected_revision='second-revision',expected_contract=capture_contract([requirement]).digest,
            policy_digest='c'*64,runner_version='fixture-runner',budget_seconds=60)
        verification.record_report(owner='owner',request_id=second_check.id,
            results=[{'key':'page','checkIndex':0,'passed':True,'note':'fixture'}])
        releases.publish(owner='owner',project_id='p',release_id='second-http',verification_id=second_check.id,
            expected_revision='second-revision',expected_generation=5,policy_digest='c'*64,runner_version='fixture-runner',audience='public',slug='site')
        ready_binding=await client.get(hosts.sharing_url('site'))
        assert ready_binding.status_code==307
        assert ready_binding.headers['location']==hosts.url(content.sharing_binding(slug='site').id)
        second_binding=content.bind(owner='owner',project_id='p',release_id='second-http')
        shared=await client.get(hosts.sharing_url('site'))
        assert shared.status_code==307 and shared.headers['location']==hosts.url(second_binding.id)
        # Publication changed between initial HTML and these resource requests.
        old_css=await client.get('/style.css')
        assert old_css.text==css.text and old_css.headers['x-atom-release']=='http-release'
        new_page=await client.get(hosts.url(second_binding.id))
        new_css=await client.get(hosts.url(second_binding.id)+'style.css')
        assert new_page.text==(changed/'index.html').read_text()
        assert new_css.text==(changed/'style.css').read_text()
        assert new_css.headers['x-atom-revision']=='second-revision'
        # Range/conditional hints never bypass authorization or select a new version.
        conditional={'range':'bytes=0-3','if-none-match':'*','if-modified-since':'Thu, 01 Oct 2099 00:00:00 GMT'}
        repeated=await client.get('/style.css',headers=conditional)
        assert repeated.status_code==200 and repeated.content==css.content
        releases.publish(owner='owner',project_id='p',release_id='private-http',verification_id=second_check.id,
            expected_revision='second-revision',expected_generation=6,policy_digest='c'*64,runner_version='fixture-runner',audience='owner',slug='site')
        # Current privacy applies even to a previously public, pinned hostname.
        assert (await client.get('/')).status_code==404
        denied_share=await client.get(hosts.sharing_url('site'),headers={'cookie':'session=owner'})
        assert denied_share.status_code==404 and 'location' not in denied_share.headers
        private=content.bind(owner='owner',project_id='p',release_id='private-http')
        assert (await client.get(hosts.url(private.id),headers={'cookie':'session=owner','authorization':'Bearer owner'})).status_code==404
        assert (await client.head('/',headers=conditional)).status_code==404
        assert (await client.get(hosts.url(second_binding.id)+'style.css',headers=conditional)).status_code==404
        releases.unpublish(owner='owner',project_id='p',command_id='http-off',expected_release='private-http',expected_generation=7)
        assert (await client.get('/style.css')).status_code==404
        assert (await client.get(hosts.sharing_url('site'))).status_code==404
        assert not list(Path('/tmp').glob('atom-release-*'))
        migrate(settings.db_path,Path('/tmp/data/before-private.db'),target_version=4)
        from app.content_access import ContentAccessRepository
        from app.content_cookies import CONTENT_COOKIE
        releases.publish(owner='owner',project_id='p',release_id='authenticated-private',verification_id=second_check.id,
            expected_revision='second-revision',expected_generation=8,policy_digest='c'*64,runner_version='fixture-runner',audience='owner',slug='site')
        private_binding=content.bind(owner='owner',project_id='p',release_id='authenticated-private')
        access=ContentAccessRepository(settings.db_path)
        protected=ContentService(content,store,hosts,access=access)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=protected),base_url=hosts.url(private_binding.id)) as authorized:
            assert (await authorized.get('/')).status_code==404
            assert (await authorized.get('/',headers={'cookie':'atom_session='+issue_session('owner')})).status_code==404
            for stage in ('read','extraction'):
                source=access.create_console_session(user_id='owner',lifetime_seconds=60)
                bootstrap=access.bootstrap(binding_id=private_binding.id)
                handoff=access.issue_handoff(viewer_id='owner',source_session_id=source.id,
                    binding_id=private_binding.id,challenge=bootstrap.challenge)
                from http.cookies import SimpleCookie
                from app.content_cookies import BOOTSTRAP_COOKIE
                exchange=await authorized.post('/_atom/exchange',content=handoff.secret.encode(),headers={
                    'origin':hosts.url(private_binding.id).rstrip('/'),'content-type':'application/octet-stream',
                    'cookie':BOOTSTRAP_COOKIE+'='+bootstrap.secret})
                assert exchange.status_code==204 and exchange.content==b''
                parsed=SimpleCookie()
                for value in exchange.headers.get_list('set-cookie'):parsed.load(value)
                cookie={'cookie':CONTENT_COOKIE+'='+parsed[CONTENT_COOKIE].value}
                result=await authorized.get('/',headers=cookie)
                assert result.status_code==200 and result.text==(changed/'index.html').read_text()
                assert result.headers['x-atom-revision']=='second-revision'
                assert (await authorized.head('/',headers=cookie)).status_code==200
                assert (await authorized.get('/style.css',headers=cookie)).text==(changed/'style.css').read_text()
                assert (await authorized.get(hosts.url(binding.id),headers=cookie)).status_code==404
                assert (await authorized.get('/',headers={'cookie':cookie['cookie']+'; '+cookie['cookie']})).status_code==404
                if stage=='read':
                    original_read=store.read
                    def revoke_read(key):
                        payload=original_read(key)
                        access.revoke_console_session(user_id='owner',session_id=source.id)
                        return payload
                    store.read=revoke_read
                else:
                    original_receive=release_view.receive_snapshot
                    def revoke_extract(stream,path):
                        received=original_receive(stream,path)
                        access.revoke_console_session(user_id='owner',session_id=source.id)
                        return received
                    release_view.receive_snapshot=revoke_extract
                try:
                    revoked=await authorized.get('/',headers=cookie)
                    assert revoked.status_code==404 and revoked.content==b''
                finally:
                    if stage=='read':store.read=original_read
                    else:release_view.receive_snapshot=original_receive
                assert (await authorized.get('/style.css',headers=cookie)).status_code==404
                assert not list(Path('/tmp').glob('atom-release-*'))
asyncio.run(content_test())
# Real artifact preflight, including races while no SQLite writer lock is held.
import sqlite3
from app.artifacts import ArtifactError
with sqlite3.connect(settings.db_path) as db:
    check_id,=db.execute("SELECT verification_id FROM release_records WHERE id='authenticated-private'").fetchone()
intent=dict(owner='owner',project_id='p',release_id='preflight',verification_id=check_id,
    expected_revision='second-revision',expected_generation=9,policy_digest='c'*64,
    runner_version='fixture-runner',audience='public',slug='site')
def publication_state():
    with sqlite3.connect(settings.db_path) as db:
        return {table:db.execute('SELECT * FROM '+table+' ORDER BY 1').fetchall()
            for table in ('release_records','release_publications','content_bindings','command_receipts')}
before=publication_state()
original_read=store.read
reads=[]
def forbidden_read(key):
    reads.append(key)
    raise AssertionError('unauthorized or replay storage read')
store.read=forbidden_read
try:
    try:releases.publish_verified(store,**(intent|{'owner':'other'}));raise AssertionError('foreign publish')
    except VerificationError as error:assert str(error)=='release_not_found'
finally:store.read=original_read
assert not reads and publication_state()==before
candidate=releases._publish(**intent,_preflight=True)
artifact_file=store.root/(candidate.key+'.atomsnap')
actual=artifact_file.read_bytes()
try:
    artifact_file.write_bytes(b'broken')
    try:releases.publish_verified(store,**intent);raise AssertionError('corrupt publish')
    except ArtifactError:pass
finally:artifact_file.write_bytes(actual)
assert publication_state()==before
absent=store.root/'preflight-test-backup'
artifact_file.rename(absent)
try:
    try:releases.publish_verified(store,**intent);raise AssertionError('missing publish')
    except ArtifactError:pass
finally:absent.rename(artifact_file)
assert publication_state()==before
# A substituted valid snapshot must not be mistaken for the captured descriptor.
store.read=lambda key: original_payload
try:
    try:releases.publish_verified(store,**intent);raise AssertionError('substituted publish')
    except ArtifactError as error:assert str(error)=='release_artifact_mismatch'
finally:store.read=original_read
assert publication_state()==before
# Concurrent real unpublish during storage IO must win over stale preflight.
def unpublish_during_read(key):
    payload=original_read(key)
    releases.unpublish(owner='owner',project_id='p',command_id='preflight-off',
        expected_release='authenticated-private',expected_generation=9)
    return payload
store.read=unpublish_during_read
try:
    try:releases.publish_verified(store,**intent);raise AssertionError('stale promotion')
    except VerificationError as error:assert str(error)=='release_conflict'
finally:store.read=original_read
with sqlite3.connect(settings.db_path) as db:
    assert db.execute("SELECT release_id,generation,live FROM release_publications WHERE project_id='p'").fetchone()==('authenticated-private',10,0)
    assert db.execute("SELECT count(*) FROM release_records WHERE id='preflight'").fetchone()==(0,)
receipt=releases.publish_verified(store,**(intent|{'expected_generation':10}))
assert receipt.generation==11
releases.unpublish(owner='owner',project_id='p',command_id='after-preflight-off',expected_release='preflight',expected_generation=11)
committed=publication_state()
store.read=forbidden_read
try:
    assert releases.publish_verified(store,**(intent|{'expected_generation':10}))==receipt
finally:store.read=original_read
assert not reads and publication_state()==committed
print(json.dumps({'routes':'verified','legacy':(legacy/'index.html').read_text()}))
'''
    bootstrap="import json,sys; source=json.loads(sys.stdin.buffer.read()); exec(compile(source.pop('script'),'<revision-routes>','exec'))"
    name='atom-revision-routes-'+uuid.uuid4().hex
    try:
        code,out,err=run_bounded(['docker','run','--name',name,'--network=none','--read-only',
            '--user','1000:1000','--cap-drop=ALL','--security-opt=no-new-privileges',
            '--memory=512m','--pids-limit=128','--tmpfs','/tmp:rw,nosuid,nodev,size=256m,mode=1777',
            '--workdir','/tmp','-i',IMAGE,'/app/backend/.venv/bin/python','-I','-c',bootstrap],
            input_data=json.dumps({'script':script,'code':base64.b64encode(archive.getvalue()).decode()}).encode(),timeout=30)
        assert code==0,err.decode()
        assert json.loads(out)=={'routes':'verified','legacy':'<h1>uncommitted stale legacy</h1>'}
    finally:
        run_bounded(['docker','rm','-f',name])
