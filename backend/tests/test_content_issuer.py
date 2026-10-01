import json
import sqlite3
from urllib.parse import urlsplit

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.access_repository import AccessError
from app.artifacts import Artifact
from app.config import get_settings, Settings
from app.console_auth import DURABLE_COOKIE
from app.content_access import ContentAccessRepository
from app.content_repository import ContentRepository
from app.models import Project, Requirement
from app.release_repository import ReleaseRepository
from app.revisions import RevisionRepository
from app.verification_contract import capture_contract
from app.verification_repository import VerificationRepository
from test_durable_auth_routes import durable_client, LOGIN, ORIGIN

PATH='/api/content-access/handoff'
HEADERS={'X-Atom-Intent':'open-private-content'}


@pytest.fixture
def issuer(durable_client,monkeypatch):
    client,path=durable_client
    owner=client.post('/api/auth/register',json=LOGIN).json()['id']
    monkeypatch.setattr(get_settings(),'content_host_suffix','content.example.net')
    engine=create_engine(f'sqlite:///{path}')
    requirement={'key':'page','title':'Page','detail':'','checks':[{'type':'exists','selector':'h1'}]}
    with Session(engine) as session:
        session.add(Project(id='p',user_id=owner,title='Project',prompt='Fixture'))
        session.flush()
        session.add(Requirement(project_id='p',key='page',title='Page',detail='',checks_json=json.dumps(requirement['checks'])))
        session.commit()
    engine.dispose()
    revisions=RevisionRepository(path)
    workspace=revisions.ensure_workspace(owner,'p')
    # Descriptor/report fixtures seed scope only; no artifact/browser evidence.
    revision=revisions.bootstrap(owner,workspace,Artifact('a'*64,'b'*64,14))
    verification=VerificationRepository(path)
    request=verification.reserve(owner=owner,workspace_id=workspace,request_id='check',
        expected_revision=revision,expected_contract=capture_contract([requirement]).digest,
        policy_digest='c'*64,runner_version='fixture',budget_seconds=60)
    verification.record_report(owner=owner,request_id=request.id,
        results=[{'key':'page','checkIndex':0,'passed':True,'note':'fixture'}])
    ReleaseRepository(path).publish(owner=owner,project_id='p',release_id='release',verification_id=request.id,
        expected_revision=revision,expected_generation=0,policy_digest='c'*64,runner_version='fixture',audience='owner',slug='site')
    binding=ContentRepository(path).bind(owner=owner,project_id='p',release_id='release')
    access=ContentAccessRepository(path)
    bootstrap=access.bootstrap(binding_id=binding.id)
    return client,path,access,bootstrap,{'binding':binding.id,'challenge':bootstrap.challenge}


def test_real_login_issues_scoped_handoff_and_logout_revokes_content(issuer):
    client,path,access,bootstrap,body=issuer
    source_cookie=client.cookies.get(DURABLE_COOKIE)
    result=client.post(PATH,json=body,headers=HEADERS)
    assert result.status_code==200
    assert result.headers['cache-control']=='no-store' and result.headers['referrer-policy']=='no-referrer'
    target=urlsplit(result.json()['url'])
    assert target.scheme=='https' and target.netloc==f"r-{body['binding']}.content.example.net"
    assert target.path=='/_atom/exchange' and not target.query and len(target.fragment)==64
    session=access.exchange(binding_id=body['binding'],handoff=target.fragment,browser_nonce=bootstrap.secret)
    assert access.authorize(binding_id=body['binding'],session_secret=session.secret)
    assert client.post('/api/auth/logout').status_code==200
    with pytest.raises(AccessError):access.authorize(binding_id=body['binding'],session_secret=session.secret)
    replay=client.post(PATH,json=body,headers=HEADERS|{'Cookie':DURABLE_COOKIE+'='+source_cookie})
    assert replay.status_code==401


@pytest.mark.parametrize('change',['foreign-origin','no-intent','extra','duplicate','malformed','query','length','unauthenticated'])
def test_invalid_request_never_issues(issuer,change):
    client,path,access,bootstrap,body=issuer
    headers=dict(HEADERS);target=PATH;payload=json.dumps(body)
    if change=='foreign-origin':headers['Origin']='https://foreign.example'
    elif change=='no-intent':headers={}
    elif change=='extra':payload=json.dumps(body|{'returnUrl':'https://foreign.example'})
    elif change=='duplicate':payload='{"binding":"'+body['binding']+'",'+payload[1:]
    elif change=='malformed':payload=json.dumps(body|{'challenge':'x'})
    elif change=='query':target+='?return=https://foreign.example'
    elif change=='length':headers['Content-Length']='1'
    elif change=='unauthenticated':client.cookies.clear()
    result=client.post(target,content=payload,headers=headers|{'Content-Type':'application/json'})
    assert result.status_code>=400 and result.headers['cache-control']=='no-store'
    with sqlite3.connect(path) as db:assert db.execute('SELECT count(*) FROM content_handoffs').fetchone()==(0,)


def test_foreign_signed_user_cannot_issue_for_other_project(issuer):
    client,path,_,_,body=issuer
    assert client.post('/api/auth/register',json=LOGIN|{'email':'other@example.org'}).status_code==200
    assert client.post(PATH,json=body,headers=HEADERS).status_code==404
    with sqlite3.connect(path) as db:assert db.execute('SELECT count(*) FROM content_handoffs').fetchone()==(0,)


def test_get_does_not_issue_and_second_issue_conflicts(issuer):
    client,path,_,_,body=issuer
    assert client.get(PATH,params=body).status_code in (404,405)
    assert client.post(PATH,json=body,headers=HEADERS).status_code==200
    assert client.post(PATH,json=body,headers=HEADERS).status_code==409
    with sqlite3.connect(path) as db:assert db.execute('SELECT count(*) FROM content_handoffs').fetchone()==(1,)


@pytest.mark.parametrize('changed',[{'session_mode':'legacy'},{'content_host_suffix':'console.example.org'},
    {'content_host_suffix':'https://content.example.net'},{'content_host_suffix':'child.console.example.org'}])
def test_handoff_configuration_rejects_unsafe_combinations(changed):
    values=get_settings().model_dump()|dict(session_mode='durable',console_origin=ORIGIN,
        content_host_suffix='content.example.net',cookie_secure=True,cookie_path='/')|changed
    with pytest.raises(ValueError):Settings(**values)


def test_cancelled_issuer_retains_worker_capacity_until_real_commit(issuer,monkeypatch):
    import asyncio
    import threading
    import httpx
    from app.main import app
    from app.routers import content_access as endpoint
    client,path,_,_,body=issuer
    token=client.cookies.get(DURABLE_COOKIE)
    started=threading.Event();finish=threading.Event()
    original=endpoint._issue
    def held(*args):
        started.set()
        assert finish.wait(5)
        return original(*args)
    monkeypatch.setattr(endpoint,'_issue',held)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ORIGIN) as transport:
            task=asyncio.create_task(transport.post(PATH,json=body,headers=HEADERS|{
                'Origin':ORIGIN,'Cookie':DURABLE_COOKIE+'='+token}))
            for _ in range(100):
                if started.is_set():break
                await asyncio.sleep(.01)
            assert started.is_set()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):await task
            claimed=0
            try:
                while endpoint._ADMISSION.acquire(blocking=False):claimed+=1
                assert claimed==7 and endpoint._WORKERS
            finally:
                for _ in range(claimed):endpoint._ADMISSION.release()
                finish.set()
            for _ in range(200):
                if not endpoint._WORKERS:break
                await asyncio.sleep(.01)
            assert not endpoint._WORKERS
    try:asyncio.run(scenario())
    finally:finish.set()
    with sqlite3.connect(path) as db:assert db.execute('SELECT count(*) FROM content_handoffs').fetchone()==(1,)
