import asyncio
from http.cookies import SimpleCookie
import sqlite3
from urllib.parse import urlsplit, parse_qs

import pytest

from app.content_bootstrap import BOOTSTRAP_PATH, ContentNavigation
from app.content_cookies import BOOTSTRAP_COOKIE
from app.content_service import ContentService
from test_content_exchange import setup, request, private, content, release, ledger, legacy


def bootstrap_setup(private):
    app,scope,_=setup(private)
    app=ContentService(app.repository,None,app.hosts,access=app.access,
                       navigation=ContentNavigation('https://console.example.org'))
    scope.update(method='GET',path=BOOTSTRAP_PATH,raw_path=BOOTSTRAP_PATH.encode())
    scope['headers']=[scope['headers'][0],(b'sec-fetch-mode',b'navigate'),(b'sec-fetch-dest',b'document')]
    return app,scope


@pytest.mark.parametrize('origin',['http://console.example','https://console.example/',
    'https://user@console.example','https://console.example:443','https://console.example?x',
    'https://console.example#x','https://Console.example','https://localhost',None])
def test_console_origin_must_be_canonical(origin):
    with pytest.raises(ValueError):ContentNavigation(origin)


@pytest.mark.parametrize('origin', ['https://159.75.231.98', 'https://[2001:db8::1]'])
def test_console_origin_accepts_canonical_https_ip(origin):
    assert ContentNavigation(origin).console_origin == origin


@pytest.mark.parametrize('origin', ['https://159.75.231.98:443', 'https://159.75.231.098',
    'https://[2001:0db8::1]', 'https://[2001:db8::1]:443', 'https://159.75.231.98/atom'])
def test_console_origin_rejects_noncanonical_ip(origin):
    with pytest.raises(ValueError, match='invalid_content_console_origin'):
        ContentNavigation(origin)


@pytest.mark.parametrize('path', ['/', '//evil.test', '/atom/', '/a/../b', '/atom?x', '/%61tom', '/a\\b', None])
def test_console_base_path_rejects_ambiguous_redirects(path):
    with pytest.raises(ValueError, match='invalid_content_console_path'):
        ContentNavigation('https://console.example.org', path)


def test_console_subpath_is_preserved_in_bootstrap(private):
    app, scope = bootstrap_setup(private)
    app.navigation = ContentNavigation('https://console.example.org', '/atom')
    result = asyncio.run(request(app, scope, b''))
    assert urlsplit(dict(result[0]['headers'])[b'location'].decode()).path == '/atom/content-access'


def test_bootstrap_cookie_and_fixed_public_challenge_can_issue_handoff(private):
    app,scope=bootstrap_setup(private)
    result=asyncio.run(request(app,scope,b''))
    assert result[0]['status']==303 and result[1]['body']==b''
    headers=dict(result[0]['headers'])
    cookie=SimpleCookie();cookie.load(headers[b'set-cookie'].decode())
    nonce=cookie[BOOTSTRAP_COOKIE]
    assert nonce['httponly'] and nonce['secure'] and nonce['samesite']=='lax'
    assert nonce['path']=='/' and not nonce['domain'] and nonce['expires']
    target=urlsplit(headers[b'location'].decode())
    assert (target.scheme,target.netloc,target.path)==('https','console.example.org','/content-access')
    query=parse_qs(target.query)
    assert set(query)=={'binding','challenge'} and query['binding']==[private[2]]
    assert nonce.value not in headers[b'location'].decode()
    handoff=private[1].issue_handoff(viewer_id='user',source_session_id=private[3].id,
        binding_id=private[2],challenge=query['challenge'][0])
    assert private[1].exchange(binding_id=private[2],handoff=handoff.secret,browser_nonce=nonce.value)


@pytest.mark.parametrize('change',['HEAD','POST','query','http','alias','frame','image','missing','prefetch'])
def test_invalid_bootstrap_has_no_database_or_cookie_effect(private,change):
    app,scope=bootstrap_setup(private)
    if change in ('HEAD','POST'):scope['method']=change
    elif change=='query':scope['query_string']=b'return=https://foreign.example'
    elif change=='http':scope['scheme']='http'
    elif change=='alias':scope['raw_path']=b'/%5fatom/bootstrap'
    elif change=='frame':scope['headers'][-1]=(b'sec-fetch-dest',b'iframe')
    elif change=='image':scope['headers'][-1]=(b'sec-fetch-dest',b'image')
    elif change=='missing':scope['headers']=scope['headers'][:1]
    elif change=='prefetch':scope['headers'].append((b'sec-purpose',b'prefetch'))
    with sqlite3.connect(private[0]) as db:before=db.execute('SELECT * FROM content_bootstraps').fetchall()
    result=asyncio.run(request(app,scope,b''))
    assert result[0]['status']>=400 and b'set-cookie' not in dict(result[0]['headers'])
    if change in ('HEAD','POST'):assert dict(result[0]['headers'])[b'allow']==b'GET'
    with sqlite3.connect(private[0]) as db:assert db.execute('SELECT * FROM content_bootstraps').fetchall()==before


def test_navigation_requires_access_and_separate_host_configuration(private):
    app,scope=bootstrap_setup(private)
    with pytest.raises(ValueError,match='requires_access'):
        ContentService(app.repository,None,app.hosts,navigation=app.navigation)
    for origin in ('https://content.example','https://console.content.example'):
        with pytest.raises(ValueError,match='overlapping'):
            ContentService(app.repository,None,app.hosts,access=app.access,navigation=ContentNavigation(origin))
