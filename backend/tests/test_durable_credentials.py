import sqlite3
import time

import jwt
import pytest

from app.access_repository import AccessError, AccessRepository
from app.durable_credentials import DurableConsoleCredentials
from app.migrations import migrate
from test_revision_migrations import legacy

KEY='synthetic-credential-test-key-32-characters'


@pytest.fixture
def credentials(legacy):
    path,backup=legacy
    migrate(path,backup,target_version=4)
    repository=AccessRepository(path)
    session=repository.create_console_session(user_id='user',lifetime_seconds=300)
    codec=DurableConsoleCredentials(repository,key=KEY,issuer='test-console',audience='test-web')
    return path,repository,session,codec


def claims(session):
    return dict(iss='test-console',aud='test-web',sub=session.user_id,sid=session.id,
                iat=session.created_at,exp=session.expires_at,v=1)


def signed(payload,**options):
    return jwt.encode(payload,options.get('key',KEY),algorithm=options.get('algorithm','HS256'),
                      headers=options.get('headers',{'typ':'atom-console+jwt'}))


def test_real_signature_session_and_revocation(credentials):
    _,repository,session,codec=credentials
    token=codec.sign(user_id='user',session_id=session.id)
    assert codec.authenticate(token)==session
    repository.revoke_console_session(user_id='user',session_id=session.id)
    assert codec.authenticate(token) is None
    with pytest.raises(AccessError):codec.sign(user_id='user',session_id=session.id)


@pytest.mark.parametrize('mutation',[{'iss':'foreign'},{'aud':'foreign'},{'aud':['test-web']},
    {'sub':'foreign'},{'sid':'f'*32},{'v':True},{'v':2},{'iat':True},{'extra':'unrecognized'},
    {'exp':1},{'exp':float('inf')},{'iat':float('nan')},{'sid':None}])
def test_claim_scope_version_and_types_are_strict(credentials,mutation):
    _,_,session,codec=credentials
    assert codec.authenticate(signed(claims(session)|mutation)) is None


def test_signed_lifetime_cannot_change_persisted_lifetime(credentials):
    _,_,session,codec=credentials
    for mutation in ({'exp':session.expires_at+1},{'iat':session.created_at-1}):
        assert codec.authenticate(signed(claims(session)|mutation)) is None


def test_legacy_subject_only_token_is_rejected(credentials):
    _,_,session,codec=credentials
    assert codec.authenticate(signed({'sub':'user','iat':session.created_at,'exp':session.expires_at})) is None
    assert codec.authenticate(jwt.encode(claims(session),KEY,algorithm='HS256')) is None


@pytest.mark.parametrize('options',[{'key':'different-synthetic-key-at-least-32-long'},
    {'algorithm':'HS512'},{'algorithm':'none','key':None},{'headers':{'typ':'JWT'}},{'headers':{'typ':'atom-console+jwt','kid':'untrusted'}}])
def test_signature_algorithm_and_header_rejected_before_ledger(credentials,monkeypatch,options):
    _,repository,session,codec=credentials
    def unexpected(**_):raise AssertionError('unverified credential reached ledger')
    monkeypatch.setattr(repository,'console_session',unexpected)
    assert codec.authenticate(signed(claims(session),**options)) is None


@pytest.mark.parametrize('token',[None,True,b'token','', 'x'*4097,'malformed.jwt.data'])
def test_invalid_input_is_denied(credentials,token):
    assert credentials[3].authenticate(token) is None


def test_storage_failure_is_not_silently_treated_as_logout(credentials):
    path,_,session,codec=credentials
    token=codec.sign(user_id='user',session_id=session.id)
    with sqlite3.connect(path) as db:db.execute('ALTER TABLE users ADD COLUMN unexpected TEXT')
    with pytest.raises(AccessError,match='access_unavailable'):codec.authenticate(token)


def test_expired_and_future_tokens_are_rejected(credentials):
    _,_,session,codec=credentials
    assert codec.authenticate(signed(claims(session)|{'exp':int(time.time())-1})) is None
    assert codec.authenticate(signed(claims(session)|{'iat':int(time.time())+600})) is None


@pytest.mark.parametrize('values',[{'key':'short'},{'key':None},{'issuer':''},{'audience':'invalid audience'}])
def test_invalid_configuration(credentials,values):
    with pytest.raises(ValueError,match='invalid_durable_credential_configuration'):
        DurableConsoleCredentials(credentials[1],**(dict(key=KEY,issuer='test-console',audience='test-web')|values))
