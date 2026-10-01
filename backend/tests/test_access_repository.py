from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import sqlite3
from threading import Barrier

import pytest

from app.access_repository import AccessError, AccessRepository
from app.migrations import migrate
from test_revision_migrations import legacy


@pytest.fixture(params=[4,5])
def access(legacy,monkeypatch,request):
    path,backup=legacy
    migrate(path,backup,target_version=request.param)
    monkeypatch.setattr('app.access_repository.time.time',lambda:100)
    return path,AccessRepository(path)


def test_session_reopen_expiry_and_clock_rollback(access,monkeypatch):
    path,repository=access
    session=repository.create_console_session(user_id='user',lifetime_seconds=60)
    assert AccessRepository(path).console_session(user_id='user',session_id=session.id)==session
    for now in (99,160):
        monkeypatch.setattr('app.access_repository.time.time',lambda:now)
        with pytest.raises(AccessError,match='session_not_found'):
            repository.console_session(user_id='user',session_id=session.id)
    monkeypatch.setattr('app.access_repository.time.time',lambda:159)
    assert repository.console_session(user_id='user',session_id=session.id)==session


def test_concurrent_revocation_is_idempotent_and_scoped(access):
    path,repository=access
    session=repository.create_console_session(user_id='user',lifetime_seconds=60)
    with pytest.raises(AccessError):repository.revoke_console_session(user_id='foreign',session_id=session.id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:repository.revoke_console_session(user_id='user',session_id=session.id),range(2)))
    assert results[0]==results[1] and results[0].revoked_at==100
    with pytest.raises(AccessError):AccessRepository(path).console_session(user_id='user',session_id=session.id)


def test_capacity_is_atomic_and_revocation_frees_slot(access):
    path,_=access
    repository=AccessRepository(path,active_sessions_per_user=1)
    barrier=Barrier(2)
    def create(_):
        barrier.wait(timeout=3)
        try:return repository.create_console_session(user_id='user',lifetime_seconds=60)
        except AccessError as error:
            assert str(error)=='session_capacity'
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(create,range(2)))
    winner,=[result for result in results if result is not None]
    repository.revoke_console_session(user_id='user',session_id=winner.id)
    assert repository.create_console_session(user_id='user',lifetime_seconds=60).id!=winner.id


def test_collision_never_overwrites_session(access,monkeypatch):
    path,repository=access
    session=repository.create_console_session(user_id='user',lifetime_seconds=60)
    monkeypatch.setattr('app.access_repository.secrets.token_hex',lambda _:session.id)
    with pytest.raises(AccessError,match='access_conflict'):
        repository.create_console_session(user_id='user',lifetime_seconds=30)
    assert repository.console_session(user_id='user',session_id=session.id)==session


def test_failed_revoke_preserves_active_session(access,monkeypatch):
    path,repository=access
    session=repository.create_console_session(user_id='user',lifetime_seconds=60)
    original=repository._transaction
    @contextmanager
    def denied():
        with original() as db:
            db.set_authorizer(lambda action,table,*_:sqlite3.SQLITE_DENY
                if action==sqlite3.SQLITE_UPDATE and table=='console_sessions' else sqlite3.SQLITE_OK)
            yield db
    monkeypatch.setattr(repository,'_transaction',denied)
    with pytest.raises(AccessError,match='access_unavailable'):
        repository.revoke_console_session(user_id='user',session_id=session.id)
    assert AccessRepository(path).console_session(user_id='user',session_id=session.id)==session


@pytest.mark.parametrize('lifetime',[0,-1,True,1.5,90*86400+1])
def test_invalid_lifetime_has_no_effect(access,lifetime):
    path,repository=access
    with pytest.raises(AccessError):repository.create_console_session(user_id='user',lifetime_seconds=lifetime)
    with sqlite3.connect(path) as db:assert db.execute('SELECT count(*) FROM console_sessions').fetchone()==(0,)


def test_v3_is_not_silently_upgraded(legacy):
    path,backup=legacy
    migrate(path,backup,target_version=3)
    with pytest.raises(AccessError,match='access_schema_required'):AccessRepository(path)


def test_expired_session_frees_capacity_without_extending_history(access,monkeypatch):
    path,_=access
    repository=AccessRepository(path,active_sessions_per_user=1)
    first=repository.create_console_session(user_id='user',lifetime_seconds=1)
    monkeypatch.setattr('app.access_repository.time.time',lambda:101)
    second=repository.create_console_session(user_id='user',lifetime_seconds=60)
    assert second.id!=first.id
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT created_at,expires_at,revoked_at FROM console_sessions WHERE id=?',(first.id,)).fetchone()==(100,101,None)


def test_unknown_user_and_foreign_session_are_denied(access):
    path,repository=access
    with pytest.raises(AccessError):repository.create_console_session(user_id='foreign',lifetime_seconds=60)
    session=repository.create_console_session(user_id='user',lifetime_seconds=60)
    for user,identity in [('foreign',session.id),('user','A'*32),('user','../session')]:
        with pytest.raises(AccessError):repository.console_session(user_id=user,session_id=identity)
    assert repository.console_session(user_id='user',session_id=session.id)==session


def test_existing_repository_rejects_schema_drift(access):
    path,repository=access
    with sqlite3.connect(path) as db:db.execute('ALTER TABLE users ADD COLUMN unexpected TEXT')
    with pytest.raises(AccessError,match='access_unavailable'):
        repository.create_console_session(user_id='user',lifetime_seconds=60)


@pytest.mark.parametrize('options',[{'active_sessions_per_user':0},{'active_sessions_per_user':True},
    {'active_sessions_per_user':129},{'lock_timeout':float('nan')},{'lock_timeout':True}])
def test_invalid_configuration_fails_before_io(access,options):
    with pytest.raises(AccessError,match='invalid_access_configuration'):AccessRepository(access[0],**options)


def test_account_revoke_is_scoped_and_old_source_cannot_revoke_new_login(access):
    path,repository=access
    sessions=[repository.create_console_session(user_id='user',lifetime_seconds=60) for _ in range(3)]
    with pytest.raises(AccessError):
        repository.revoke_console_sessions(user_id='foreign',source_session_id=sessions[0].id)
    assert repository.revoke_console_sessions(user_id='user',source_session_id=sessions[0].id)==3
    for session in sessions:
        with pytest.raises(AccessError):repository.console_session(user_id='user',session_id=session.id)
    fresh=repository.create_console_session(user_id='user',lifetime_seconds=60)
    with pytest.raises(AccessError):
        repository.revoke_console_sessions(user_id='user',source_session_id=sessions[0].id)
    assert AccessRepository(path).console_session(user_id='user',session_id=fresh.id)==fresh


def test_account_revoke_rolls_back_all_rows_on_late_failure(access,monkeypatch):
    path,repository=access
    sessions=[repository.create_console_session(user_id='user',lifetime_seconds=60) for _ in range(3)]
    original=repository._transaction
    @contextmanager
    def late_failure():
        with original() as db:
            yield db
            raise sqlite3.OperationalError('test_commit_failure')
    monkeypatch.setattr(repository,'_transaction',late_failure)
    with pytest.raises(AccessError,match='access_unavailable'):
        repository.revoke_console_sessions(user_id='user',source_session_id=sessions[0].id)
    reopened=AccessRepository(path)
    for session in sessions:assert reopened.console_session(user_id='user',session_id=session.id)==session


def test_account_revoke_and_new_login_serialize_without_partial_existing_state(access):
    _,repository=access
    old=[repository.create_console_session(user_id='user',lifetime_seconds=60) for _ in range(3)]
    barrier=Barrier(2)
    def revoke():
        barrier.wait(timeout=3)
        return repository.revoke_console_sessions(user_id='user',source_session_id=old[0].id)
    def create():
        barrier.wait(timeout=3)
        return repository.create_console_session(user_id='user',lifetime_seconds=60)
    with ThreadPoolExecutor(max_workers=2) as pool:
        revocation=pool.submit(revoke);creation=pool.submit(create)
        count=revocation.result();fresh=creation.result()
    for session in old:
        with pytest.raises(AccessError):repository.console_session(user_id='user',session_id=session.id)
    if count==4:
        with pytest.raises(AccessError):repository.console_session(user_id='user',session_id=fresh.id)
    else:
        assert count==3 and repository.console_session(user_id='user',session_id=fresh.id)==fresh


def test_account_revoke_clock_rollback_is_atomic(access,monkeypatch):
    path,repository=access
    source=repository.create_console_session(user_id='user',lifetime_seconds=60)
    monkeypatch.setattr('app.access_repository.time.time',lambda:110)
    repository.create_console_session(user_id='user',lifetime_seconds=60)
    monkeypatch.setattr('app.access_repository.time.time',lambda:105)
    with pytest.raises(AccessError,match='invalid_access_clock'):
        repository.revoke_console_sessions(user_id='user',source_session_id=source.id)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM console_sessions WHERE revoked_at IS NULL').fetchone()==(2,)
