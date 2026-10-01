import sqlite3

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.access_repository import AccessError, AccessRepository
from app.config import Settings, get_settings
from app.console_auth import DURABLE_COOKIE
from app.db import get_db
from app.main import app
from app.migrations import migrate
from app.models import Base
from app.security import issue_session

ORIGIN='https://console.example.org'
LOGIN={'email':'durable@example.org','password':'Actual-test-password-913!'}


@pytest.fixture
def durable_client(tmp_path,monkeypatch):
    path=tmp_path/'auth.db'
    engine=create_engine(f'sqlite:///{path}',connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine)
    migrate(path,tmp_path/'before-v4.db',target_version=4)
    settings=get_settings()
    for key,value in dict(db_path=path,session_mode='durable',console_origin=ORIGIN,
                          cookie_secure=True,cookie_path='/').items():
        monkeypatch.setattr(settings,key,value)
    def database():
        with Session(engine,expire_on_commit=False) as session:yield session
    app.dependency_overrides[get_db]=database
    # Actual application routes/dependencies, but no runtime/orchestrator lifespan.
    client=TestClient(app,base_url=ORIGIN,headers={'Origin':ORIGIN})
    try:yield client,path
    finally:
        client.close();app.dependency_overrides.pop(get_db);engine.dispose()


def test_real_password_login_and_durable_logout_reject_copied_cookie(durable_client):
    client,path=durable_client
    registered=client.post('/api/auth/register',json=LOGIN)
    assert registered.status_code==200
    token=client.cookies.get(DURABLE_COOKIE)
    assert token and 'atom_session=' not in registered.headers['set-cookie']
    assert 'Secure' in registered.headers['set-cookie'] and 'HttpOnly' in registered.headers['set-cookie']
    assert client.get('/api/auth/me').status_code==200
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM console_sessions WHERE revoked_at IS NULL').fetchone()==(1,)
    assert client.post('/api/auth/logout').status_code==200
    assert client.get('/api/auth/me',headers={'Cookie':DURABLE_COOKIE+'='+token}).status_code==401
    assert client.post('/api/auth/login',json=LOGIN|{'password':'Wrong-password-12'}).status_code==401
    assert client.post('/api/auth/login',json=LOGIN).status_code==200
    assert client.cookies.get(DURABLE_COOKIE)!=token and client.get('/api/auth/me').status_code==200
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM console_sessions').fetchone()==(2,)
        assert db.execute('SELECT count(*) FROM console_sessions WHERE revoked_at IS NOT NULL').fetchone()==(1,)


def test_legacy_and_ambiguous_credentials_are_not_accepted(durable_client,monkeypatch):
    client,path=durable_client
    user=client.post('/api/auth/register',json=LOGIN).json()
    current=client.cookies.get(DURABLE_COOKIE)
    monkeypatch.setattr(get_settings(),'session_mode','legacy')
    old=issue_session(user['id'])
    monkeypatch.setattr(get_settings(),'session_mode','durable')
    for cookie in ('atom_session='+old,DURABLE_COOKIE+'='+old,
                   f'{DURABLE_COOKIE}={current}; {DURABLE_COOKIE}={current}'):
        assert client.get('/api/auth/me',headers={'Cookie':cookie}).status_code==401


@pytest.mark.parametrize('endpoint',['register','login','logout'])
def test_wrong_origin_does_not_mutate_sessions(durable_client,endpoint):
    client,path=durable_client
    response=client.post('/api/auth/'+endpoint,json=LOGIN,headers={'Origin':'https://foreign.example'})
    assert response.status_code==403 and 'set-cookie' not in response.headers
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM console_sessions').fetchone()==(0,)
        assert db.execute('SELECT count(*) FROM users').fetchone()==(0,)


def test_revocation_storage_failure_never_reports_logout_success(durable_client,monkeypatch):
    client,path=durable_client
    assert client.post('/api/auth/register',json=LOGIN).status_code==200
    def unavailable(self,**kwargs):raise AccessError('access_unavailable')
    monkeypatch.setattr(AccessRepository,'revoke_console_session',unavailable)
    response=client.post('/api/auth/logout')
    assert response.status_code==503 and 'set-cookie' not in response.headers
    assert client.get('/api/auth/me').status_code==200
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT revoked_at FROM console_sessions').fetchone()==(None,)


@pytest.mark.parametrize('changed',[{'cookie_secure':False},{'cookie_path':'/api'},
    {'console_origin':None},{'console_origin':'http://console.example.org'}])
def test_durable_configuration_requires_secure_explicit_origin(changed):
    values=get_settings().model_dump()|dict(session_mode='durable',console_origin=ORIGIN,
                                          cookie_secure=True,cookie_path='/')|changed
    with pytest.raises(ValueError):Settings(**values)


def test_missing_or_duplicate_origin_denies_authenticated_logout(durable_client):
    client,path=durable_client
    assert client.post('/api/auth/register',json=LOGIN).status_code==200
    client.headers.pop('origin')
    for headers in ({}, [('Origin',ORIGIN),('Origin',ORIGIN)]):
        response=client.post('/api/auth/logout',headers=headers)
        assert response.status_code==403 and 'set-cookie' not in response.headers
    assert client.get('/api/auth/me').status_code==200


def test_durable_schema_failure_is_unavailable_not_anonymous(durable_client):
    client,path=durable_client
    assert client.post('/api/auth/register',json=LOGIN).status_code==200
    with sqlite3.connect(path) as db:db.execute('PRAGMA user_version=3')
    response=client.get('/api/auth/me')
    assert response.status_code==503 and 'set-cookie' not in response.headers


ACCOUNT_INTENT={'X-Atom-Intent':'revoke-account-sessions'}

def test_logout_all_revokes_existing_devices_but_not_future_login(durable_client):
    client,path=durable_client
    client.post('/api/auth/register',json=LOGIN)
    first=client.cookies.get(DURABLE_COOKIE)
    assert client.get('/api/auth/me').json()['canRevokeSessions'] is True
    client.post('/api/auth/login',json=LOGIN)
    second=client.cookies.get(DURABLE_COOKIE)
    client.post('/api/auth/register',json=LOGIN|{'email':'independent@example.org'})
    other=client.cookies.get(DURABLE_COOKIE)
    response=client.post('/api/auth/logout-all',headers=ACCOUNT_INTENT|{'Cookie':DURABLE_COOKIE+'='+second})
    assert response.status_code==200 and response.headers['cache-control']=='no-store'
    assert DURABLE_COOKIE not in client.cookies
    assert client.get('/api/auth/me',headers={'Cookie':DURABLE_COOKIE+'='+other}).status_code==200
    for token in (first,second):
        assert client.get('/api/auth/me',headers={'Cookie':DURABLE_COOKIE+'='+token}).status_code==401
    assert client.post('/api/auth/login',json=LOGIN).status_code==200
    assert client.post('/api/auth/logout-all',headers=ACCOUNT_INTENT|{'Cookie':DURABLE_COOKIE+'='+first}).status_code==401
    assert client.get('/api/auth/me').status_code==200


@pytest.mark.parametrize('failure',['origin','intent','storage'])
def test_logout_all_failure_does_not_clear_cookie_or_session(durable_client,monkeypatch,failure):
    client,path=durable_client
    client.post('/api/auth/register',json=LOGIN)
    headers=ACCOUNT_INTENT.copy()
    if failure=='origin':headers['Origin']='https://foreign.example'
    elif failure=='intent':headers={}
    else:
        def denied(*args,**kwargs):raise AccessError('access_unavailable')
        monkeypatch.setattr(AccessRepository,'revoke_console_sessions',denied)
    response=client.post('/api/auth/logout-all',headers=headers)
    assert response.status_code==(503 if failure=='storage' else 403)
    assert 'set-cookie' not in response.headers
    assert client.get('/api/auth/me').status_code==200
