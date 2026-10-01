import sqlite3
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.parametrize('audit_schema_version', [5, 6, 7, 9, 10])
from app.access_repository import AccessRepository, AccessError
from app.migrations import migrate
from test_revision_migrations import legacy
from test_durable_auth_routes import durable_client, LOGIN


@pytest.fixture
def audited(legacy,audit_schema_version):
    path,backup=legacy
    migrate(path,backup,target_version=audit_schema_version)
    return path,AccessRepository(path)


def events(path):
    with sqlite3.connect(path) as db:
        return db.execute('SELECT event_kind,actor_id,scope_id,source_session_id,affected_count FROM security_audit_events ORDER BY sequence').fetchall()


def test_actual_transitions_and_replay_have_exact_audit_count(audited):
    path,repository=audited
    first=repository.create_console_session(user_id='user',lifetime_seconds=60)
    second=repository.create_console_session(user_id='user',lifetime_seconds=60)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _:repository.revoke_console_session(user_id='user',session_id=first.id),range(2)))
    assert repository.revoke_console_sessions(user_id='user',source_session_id=second.id)==1
    assert events(path)==[
        ('console.session.created','user','user',first.id,1),
        ('console.session.created','user','user',second.id,1),
        ('console.session.revoked','user','user',first.id,1),
        ('console.account_sessions.revoked','user','user',second.id,1)]
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM security_audit_delivery').fetchone()==(0,)


@pytest.mark.parametrize('operation',['create','single','account'])
@pytest.mark.parametrize('failure',['audit_insert','after_audit'])
def test_business_and_audit_roll_back_together(audited,monkeypatch,operation,failure):
    path,repository=audited
    source=repository.create_console_session(user_id='user',lifetime_seconds=60)
    before=events(path)
    original=repository._transaction
    @contextmanager
    def failing():
        with original() as db:
            if failure=='audit_insert':
                db.set_authorizer(lambda action,table,*_:sqlite3.SQLITE_DENY
                    if action==sqlite3.SQLITE_INSERT and table=='security_audit_events' else sqlite3.SQLITE_OK)
            yield db
            if failure=='after_audit':raise sqlite3.OperationalError('test_late_failure')
    monkeypatch.setattr(repository,'_transaction',failing)
    with pytest.raises(AccessError):
        if operation=='create':repository.create_console_session(user_id='user',lifetime_seconds=60)
        elif operation=='single':repository.revoke_console_session(user_id='user',session_id=source.id)
        else:repository.revoke_console_sessions(user_id='user',source_session_id=source.id)
    assert events(path)==before
    with sqlite3.connect(path) as db:assert db.execute('SELECT count(*) FROM console_sessions').fetchone()==(1,)
    assert AccessRepository(path).console_session(user_id='user',session_id=source.id)==source


def test_event_identity_collision_cannot_overwrite_or_commit_business_change(audited,monkeypatch):
    path,repository=audited
    repository.create_console_session(user_id='user',lifetime_seconds=60)
    with sqlite3.connect(path) as db:event_id=db.execute('SELECT event_id FROM security_audit_events').fetchone()[0]
    monkeypatch.setattr('app.security_audit.uuid4',lambda:SimpleNamespace(hex=event_id))
    before=events(path)
    with pytest.raises(AccessError):repository.create_console_session(user_id='user',lifetime_seconds=60)
    assert events(path)==before
    with sqlite3.connect(path) as db:assert db.execute('SELECT count(*) FROM console_sessions').fetchone()==(1,)


def test_real_auth_api_commits_redacted_events(durable_client,tmp_path,audit_schema_version):
    client,path=durable_client
    migrate(path,tmp_path/'before-audited-auth.db',target_version=audit_schema_version)
    assert client.post('/api/auth/register',json=LOGIN).status_code==200
    from app.console_auth import DURABLE_COOKIE
    first=client.cookies.get(DURABLE_COOKIE)
    assert client.post('/api/auth/login',json=LOGIN).status_code==200
    second=client.cookies.get(DURABLE_COOKIE)
    assert client.post('/api/auth/logout-all',headers={'X-Atom-Intent':'revoke-account-sessions'}).status_code==200
    with sqlite3.connect(path) as db:
        rows=db.execute('SELECT * FROM security_audit_events ORDER BY sequence').fetchall()
        kinds=db.execute('SELECT event_kind,affected_count FROM security_audit_events ORDER BY sequence').fetchall()
    assert kinds==[('console.session.created',1),('console.session.created',1),('console.account_sessions.revoked',2)]
    encoded=repr(rows)
    for sensitive in (first,second,LOGIN['password'],LOGIN['email']):assert sensitive not in encoded
