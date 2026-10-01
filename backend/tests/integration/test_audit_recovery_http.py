import asyncio
import os
import secrets
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.audit_archive import encode_archive
from app.sandbox.audit_recovery import AuditRecoveryOperations
from app.sandbox.config import BrokerConfig
from app.sandbox.grants import Grant, GrantCodec
from app.sandbox.service import create_app
from test_retention_plan import planned, reader, audited_release, release, ledger, legacy

IMAGE = os.environ.get('ATOM_TEST_DOCKER_IMAGE')
pytestmark = pytest.mark.skipif(not IMAGE,reason='requires explicit pinned sandbox image')
URL = '/v1/admin/audit/recover'


@pytest.fixture
def recovery(planned,tmp_path,monkeypatch):
    _, repo = planned
    plan = repo.plan(policy_id='policy',expected_generation=1)
    policy = plan['context']['policy']
    archive = encode_archive(events=[item['event'] for item in plan['items']],context_sha256=plan['context_sha256'],
        plan_sha256=plan['plan_sha256'],scope_kind=policy['scope_kind'],scope_id=policy['scope_id'],
        event_kind=policy['event_kind'],after=0,upper_sequence=plan['upper_sequence'])
    monkeypatch.setattr(time,'time',lambda: time.time_ns()/1e9)
    config = BrokerConfig(tmp_path/'broker.db',IMAGE,secrets.token_urlsafe(32),secrets.token_urlsafe(32),sweep_seconds=60)
    headers = {'authorization':'Bearer '+config.admin_token,'content-type':'application/octet-stream',
               'x-atom-archive-sha256':archive.sha256}
    return create_app(config),config,archive,headers,plan


def test_real_admin_boundary_valid_recovery_and_denials(recovery):
    app,config,archive,headers,plan = recovery
    with TestClient(app) as client:
        assert client.post(URL,content=archive.payload).status_code == 401
        now = int(time.time())
        token = GrantCodec(config.grant_key.encode()).issue(Grant('g','o','p','r','a',1,'a'*64,now,now+60))
        assert client.post(URL,content=archive.payload,headers={**headers,'authorization':'Bearer '+token}).status_code == 401
        for changed,status in (({'x-atom-archive-sha256':'invalid'},400),({'content-type':'application/json'},415),
                               ({'content-encoding':'gzip'},415),({'x-atom-archive-sha256':'0'*64},400)):
            assert client.post(URL,content=archive.payload,headers={**headers,**changed}).status_code == status
        assert client.post(URL,content=b'x'*262145,headers=headers).status_code == 413
        assert client.post(URL,content=archive.payload,headers=[*headers.items(),('x-atom-archive-sha256',archive.sha256)]).status_code == 400
        assert not app.state.lifecycle.driver.owned_inventory()
        result = client.post(URL,content=archive.payload,headers=headers)
        assert result.status_code == 200,result.text
        assert result.headers['cache-control'] == 'no-store'
        assert result.json()['protocol'] == 'audit-recovery-v2'
        assert result.json()['result']['events'] == [item['event'] for item in plan['items']]
        assert not app.state.lifecycle.driver.owned_inventory() and not app.state.transfer_lock.locked()


def test_cancelled_request_retains_slot_until_worker_cleanup(recovery,monkeypatch):
    app,_,archive,headers,_ = recovery
    entered,release_worker = threading.Event(),threading.Event()
    original = AuditRecoveryOperations.execute
    def execute(self,*args,**kwargs):
        entered.set()
        assert release_worker.wait(10)
        return original(self,*args,**kwargs)
    monkeypatch.setattr(AuditRecoveryOperations,'execute',execute)
    async def run():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://broker') as client:
                task = asyncio.create_task(client.post(URL,content=archive.payload,headers=headers))
                try:
                    assert await asyncio.to_thread(entered.wait,10)
                    task.cancel()
                    await asyncio.sleep(.05)
                    assert not task.done() and app.state.transfer_lock.locked()
                    task.cancel()
                    await asyncio.sleep(.05)
                    assert not task.done() and app.state.transfer_lock.locked()
                    rejected = await client.post(URL,content=archive.payload,headers=headers)
                    assert rejected.status_code == 503 and rejected.json()['error'] == 'broker_busy'
                finally:
                    release_worker.set()
                with pytest.raises(asyncio.CancelledError): await task
                assert not app.state.transfer_lock.locked()
                assert not await asyncio.to_thread(app.state.lifecycle.driver.owned_inventory)
                assert app.state.lifecycle.registry.unterminated() == []
    asyncio.run(run())


def test_response_cancellation_releases_slot_after_confirmed_cleanup(recovery):
    app,_,archive,headers,_ = recovery
    async def run():
        async with app.router.lifespan_context(app):
            entered = asyncio.Event()
            async def receive(): return {'type':'http.request','body':archive.payload,'more_body':False}
            async def send(message):
                if message['type'] == 'http.response.body':
                    entered.set()
                    await asyncio.Event().wait()
            scope = {'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST','scheme':'http',
                'path':URL,'raw_path':URL.encode(),'query_string':b'',
                'headers':[(key.encode(),value.encode()) for key,value in headers.items()],
                'server':('broker',80),'client':('client',1234)}
            task = asyncio.create_task(app(scope,receive,send))
            await asyncio.wait_for(entered.wait(),15)
            assert app.state.transfer_lock.locked()
            assert not await asyncio.to_thread(app.state.lifecycle.driver.owned_inventory)
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
            assert not app.state.transfer_lock.locked()
    asyncio.run(run())
