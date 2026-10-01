import asyncio
import sqlite3
from http.cookies import SimpleCookie

import pytest

from app.content_cookies import BOOTSTRAP_COOKIE, CONTENT_COOKIE
from app.content_exchange import EXCHANGE_PATH, SCRIPT
from app.content_hosts import ContentHosts
from app.content_repository import ContentRepository
from app.content_service import ContentService, ContentLimits
from test_content_access import private, issue, content, release, ledger, legacy


def setup(private):
    path, access, binding, _ = private
    nonce, handoff = issue(private)
    hosts = ContentHosts('content.example')
    app = ContentService(ContentRepository(path), None, hosts, access=access,
                         limits=ContentLimits(receive_seconds=.02))
    scope = {'type':'http', 'http_version':'1.1', 'scheme':'https', 'method':'POST',
             'path':EXCHANGE_PATH, 'raw_path':EXCHANGE_PATH.encode(), 'query_string':b'',
             'headers':[(b'host',hosts.hostname(binding).encode()),
                        (b'origin',hosts.url(binding).rstrip('/').encode()),
                        (b'content-type',b'application/octet-stream'),(b'content-length',b'64'),
                        (b'cookie',f'{BOOTSTRAP_COOKIE}={nonce.secret}'.encode())]}
    return app,scope,handoff.secret.encode()


async def request(app, scope, body, *, events=None, stall=False):
    messages=[]
    incoming=list(events or [{'type':'http.request','body':body,'more_body':False}])
    async def receive():
        if stall:await asyncio.Event().wait()
        return incoming.pop(0)
    async def send(message):messages.append(message)
    await app(scope,receive,send)
    return messages


def unconsumed(private):
    with sqlite3.connect(private[0]) as db:
        assert db.execute('SELECT consumed_at FROM content_handoffs').fetchall()==[(None,)]
        assert db.execute('SELECT count(*) FROM content_sessions').fetchone()==(0,)


def test_exchange_sets_only_scoped_http_only_cookies_and_replay_denied(private):
    app,scope,body=setup(private)
    result=asyncio.run(request(app,scope,body))
    assert result[0]['status']==204 and result[1]['body']==b''
    cookies=[v.decode() for k,v in result[0]['headers'] if k==b'set-cookie']
    assert len(cookies)==2
    parsed=SimpleCookie()
    for value in cookies:parsed.load(value)
    session=parsed[CONTENT_COOKIE]
    assert session['secure'] and session['httponly'] and session['path']=='/'
    assert session['samesite']=='lax' and not session['domain'] and session['expires']
    assert parsed[BOOTSTRAP_COOKIE]['max-age']=='0'
    principal=private[1].authorize(binding_id=private[2],session_secret=session.value)
    assert principal.source_session_id==private[3].id
    assert asyncio.run(request(app,scope,body))[0]['status']==404


@pytest.mark.parametrize('change', ['origin','duplicate-origin','no-origin','type','length',
    'transfer','encoding','duplicate-cookie','no-cookie','wrong-cookie','query','scheme','alias','host','body'])
def test_invalid_exchange_never_consumes_handoff(private,change):
    app,scope,body=setup(private)
    if change=='origin':scope['headers']=[(k,b'https://foreign.example' if k==b'origin' else v) for k,v in scope['headers']]
    elif change=='duplicate-origin':scope['headers'].append(scope['headers'][1])
    elif change=='no-origin':scope['headers']=[(k,v) for k,v in scope['headers'] if k!=b'origin']
    elif change=='type':scope['headers']=[(k,b'text/plain' if k==b'content-type' else v) for k,v in scope['headers']]
    elif change=='length':scope['headers']=[(k,b'65' if k==b'content-length' else v) for k,v in scope['headers']]
    elif change=='transfer':scope['headers'].append((b'transfer-encoding',b'chunked'))
    elif change=='encoding':scope['headers'].append((b'content-encoding',b'gzip'))
    elif change=='duplicate-cookie':scope['headers'].append(scope['headers'][-1])
    elif change=='no-cookie':scope['headers']=scope['headers'][:-1]
    elif change=='wrong-cookie':scope['headers'][-1]=(b'cookie',f'{BOOTSTRAP_COOKIE}={"f"*64}'.encode())
    elif change=='query':scope['query_string']=b'return=https://foreign.example'
    elif change=='scheme':scope['scheme']='http'
    elif change=='alias':scope['raw_path']=b'/%5fatom/exchange'
    elif change=='host':scope['headers'][0]=(b'host',b'foreign.example')
    elif change=='body':body=b'Z'*64
    assert asyncio.run(request(app,scope,body))[0]['status']>=400
    unconsumed(private)


def test_intake_timeout_overflow_disconnect_and_fragmentation(private):
    app,scope,body=setup(private)
    assert asyncio.run(request(app,scope,body,stall=True))[0]['status']==408
    assert asyncio.run(request(app,scope,body+b'x'))[0]['status']==413
    assert asyncio.run(request(app,scope,body,events=[{'type':'http.disconnect'}]))[0]['status']==400
    empty=[{'type':'http.request','body':b'','more_body':True}]*128
    assert asyncio.run(request(app,scope,body,events=empty))[0]['status']==400
    unconsumed(private)
    events=[{'type':'http.request','body':body[:20],'more_body':True},
            {'type':'http.request','body':body[20:],'more_body':False}]
    assert asyncio.run(request(app,scope,body,events=events))[0]['status']==204


def test_service_owned_page_has_separate_policy_and_no_mutation(private):
    app,scope,body=setup(private)
    scope['method']='GET'
    result=asyncio.run(request(app,scope,b''))
    assert result[0]['status']==200
    headers=dict(result[0]['headers'])
    assert b"script-src 'sha256-" in headers[b'content-security-policy']
    assert b'unsafe-inline' not in headers[b'content-security-policy']
    assert b'set-cookie' not in headers and body not in result[1]['body']
    assert SCRIPT.index('history.replaceState')<SCRIPT.index('await fetch')
    scope['method']='HEAD'
    head=asyncio.run(request(app,scope,b''))
    assert head[1]['body']==b'' and dict(head[0]['headers'])[b'content-length']==headers[b'content-length']
    unconsumed(private)


def test_cancelled_intake_releases_admission_without_consuming(private):
    app,scope,body=setup(private)
    async def scenario():
        started=asyncio.Event()
        async def receive():
            started.set()
            await asyncio.Event().wait()
        async def send(message):raise AssertionError('cancelled response')
        task=asyncio.create_task(app(scope,receive,send))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert not app._pending
        assert (await request(app,scope,body))[0]['status']==204
    asyncio.run(scenario())
