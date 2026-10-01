"""Disposable Linux browser fixture, never a production application entrypoint."""
import json
import os
import sqlite3
from pathlib import Path

os.environ.update(ATOM_ENVIRONMENT='test', ATOM_SANDBOX_MODE='local',
    ATOM_SECRET='synthetic-session-key-32-characters-long',
    ATOM_RUNTIME_TOKEN='synthetic-runtime-key-32-characters-long',
    ATOM_DATA_DIR='/tmp/data', ATOM_DB_PATH='/tmp/data/api.db', ATOM_LLM_API_KEY='',
    ATOM_RUNTIME_URL='http://127.0.0.1:1')

from app.config import get_settings
from app.db import engine, session_scope
from app.models import Base, User, Project, Requirement
from app.migrations import migrate
from app.revisions import RevisionRepository
from app.artifacts import ArtifactStore
from app.workspace_import import import_workspace
from app.verification_contract import capture_contract
from app.verification_repository import VerificationRepository
from app.release_repository import ReleaseRepository
from app.content_policy import ContentPolicyError
from app.content_repository import ContentRepository
from app.content_hosts import ContentHosts
from app.content_service import ContentService
from app.content_bootstrap import ContentNavigation
from starlette.responses import JSONResponse
import uvicorn

settings = get_settings()
Base.metadata.create_all(engine)
requirement = {'key':'page', 'title':'Page', 'detail':'', 'checks':[{'type':'exists','selector':'h1'}]}
with session_scope() as session:
    session.add(User(id='owner',email='owner@example.invalid',name='Owner',password_hash='fixture'))
    session.flush()
    session.add(Project(id='project',user_id='owner',title='Fixture',prompt='Fixture'))
    session.flush()
    session.add(Requirement(project_id='project',key='page',title='Page',detail='',checks_json=json.dumps(requirement['checks'])))
migrate(settings.db_path,Path('/tmp/data/before-v1.db'))
repository = RevisionRepository(settings.db_path)
store_root = Path('/tmp/artifacts'); store_root.mkdir(mode=0o700)
store = ArtifactStore(store_root)
workspace = Path('/tmp/workspace'); workspace.mkdir()
html = '<h1>Actual immutable artifact</h1>' + ''.join(
    f'<link rel="stylesheet" href="/style-{index}.css"><script defer src="/script-{index}.js"></script>'
    for index in range(8))
(workspace/'index.html').write_text(html)
conflict=os.environ.get('ATOM_FIXTURE_RESERVED_PATH')=='1'
private_exchange=os.environ.get('ATOM_FIXTURE_PRIVATE_EXCHANGE')=='1'
if conflict:
    (workspace/'_atom').mkdir()
    (workspace/'_atom'/'access').write_text('fixture-owned conflicting route')
for index in range(8):
    (workspace/f'style-{index}.css').write_text(f'h1 {{ --asset-{index}: {index}; }}')
    (workspace/f'script-{index}.js').write_text(f'(window.loaded ||= []).push({index});')
imported = import_workspace(repository,store,owner='owner',project_id='project',source=workspace)
migrate(settings.db_path,Path('/tmp/data/before-v3.db'),target_version=3)
verification = VerificationRepository(settings.db_path)
request = verification.reserve(owner='owner',workspace_id=imported.workspace_id,request_id='fixture-check',
    expected_revision=imported.revision_id,expected_contract=capture_contract([requirement]).digest,
    policy_digest='c'*64,runner_version='fixture-report',budget_seconds=60)
# This deliberately synthetic report seeds publication; it is not trusted browser evidence.
verification.record_report(owner='owner',request_id=request.id,
    results=[{'key':'page','checkIndex':0,'passed':True,'note':'fixture only'}])
releases = ReleaseRepository(settings.db_path)
intent=dict(owner='owner',project_id='project',release_id='fixture-release',verification_id=request.id,
    expected_revision=imported.revision_id,expected_generation=0,policy_digest='c'*64,
    runner_version='fixture-report',audience='owner' if private_exchange else 'public',slug='fixture')
if conflict:
    try:
        releases.publish_verified(store,**intent)
        raise AssertionError('conflicting artifact promoted')
    except ContentPolicyError as error:
        assert str(error)=='reserved_content_path'
    with sqlite3.connect(settings.db_path) as db:
        for table in ('release_records','release_publications','content_bindings','command_receipts'):
            assert db.execute(f'SELECT count(*) FROM {table}').fetchone()==(0,)
    # Deliberately bypass preflight only to exercise the independent serving guard.
    releases.publish(**intent)
else:
    releases.publish_verified(store,**intent)
content = ContentRepository(settings.db_path)
binding = content.bind(owner='owner',project_id='project',release_id='fixture-release')
hosts = ContentHosts('atom-content.test')
access=None
navigation=None
if private_exchange:
    from app.content_access import ContentAccessRepository
    migrate(settings.db_path,Path('/tmp/data/before-v4.db'),target_version=4)
    access=ContentAccessRepository(settings.db_path)
    source=access.create_console_session(user_id='owner',lifetime_seconds=120)
    navigation=ContentNavigation('https://console.atom-console.test')
service = ContentService(content,store,hosts,access=access,navigation=navigation)


async def fixture(scope,receive,send):
    # Local harness metadata is intentionally separate from content authority.
    if (scope['type']=='http' and scope.get('path')=='/_fixture'
            and (b'host',b'fixture.invalid') in scope.get('headers',[])):
        await JSONResponse({'host':hosts.hostname(binding.id),'revision':imported.revision_id,'conflict':conflict,'preflightChecked':True})(scope,receive,send)
    elif (private_exchange and scope['type']=='http' and scope.get('path')=='/_fixture/issue'
          and scope.get('method')=='POST' and (b'host',b'fixture.invalid') in scope.get('headers',[])):
        # Dedicated loopback harness issuer. This is NOT a console auth endpoint.
        event=await receive()
        challenge=event.get('body',b'')
        assert event['type']=='http.request' and not event.get('more_body') and len(challenge)==64
        handoff=access.issue_handoff(viewer_id='owner',source_session_id=source.id,
            binding_id=binding.id,challenge=challenge.decode('ascii'))
        await JSONResponse({'handoff':handoff.secret})(scope,receive,send)
    else:
        # This disposable wrapper models the local TLS ingress termination.
        await service(dict(scope,scheme='https') if scope['type']=='http' else scope,receive,send)


uvicorn.run(fixture,host='0.0.0.0',port=8000,proxy_headers=False,access_log=False,log_level='error')
