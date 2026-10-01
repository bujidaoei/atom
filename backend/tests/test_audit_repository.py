import sqlite3

import pytest

pytestmark = pytest.mark.parametrize('audit_schema_version', [5, 6, 7, 9])
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.access_repository import AccessRepository
from app.audit_repository import AuditRepository, AuditReadError
from app.models import User
from test_release_audit import audited_release, release, ledger, legacy


@pytest.fixture
def reader(audited_release,monkeypatch):
    path,releases,args=audited_release
    releases.publish(**args)
    monkeypatch.setattr('app.audit_repository.time.time',lambda:100)
    access=AccessRepository(path)
    source=access.create_console_session(user_id='user',lifetime_seconds=60)
    engine=create_engine('sqlite:///'+path.as_posix())
    with Session(engine) as db:
        db.add(User(id='other',email='other@example.org',name='Other',password_hash='fixture'))
        db.commit()
    engine.dispose()
    other=access.create_console_session(user_id='other',lifetime_seconds=60)
    return path,AuditRepository(path),access,source,other


def test_pages_freeze_upper_bound_and_do_not_duplicate_equal_times(reader):
    path,repository,access,source,_=reader
    for _ in range(4):access.create_console_session(user_id='user',lifetime_seconds=60)
    args=dict(user_id='user',source_session_id=source.id,limit=2)
    first=repository.page(**args)
    assert first.next_after is not None
    newer=access.create_console_session(user_id='user',lifetime_seconds=60)
    seen=list(first.events)
    cursor=first.next_after
    while cursor is not None:
        page=repository.page(**args,after=cursor,upper=first.upper)
        seen.extend(page.events);cursor=page.next_after
        assert page.upper==first.upper
    assert len(seen)==5 and len({event['event_id'] for event in seen})==5
    assert {event['occurred_at'] for event in seen}=={100}
    assert newer.id not in {event['source_session_id'] for event in seen}
    assert len(repository.page(user_id='user',source_session_id=source.id).events)==6
    assert repository.page(**args,after=first.upper,upper=first.upper).events==()


def test_account_and_project_scopes_reauthorize_each_page(reader):
    path,repository,access,source,other=reader
    own=repository.page(user_id='user',source_session_id=source.id)
    assert all(event['scope_id']=='user' and event['scope_kind']=='account' for event in own.events)
    foreign=repository.page(user_id='other',source_session_id=other.id)
    assert len(foreign.events)==1 and foreign.events[0]['actor_id']=='other'
    with pytest.raises(AuditReadError,match='access_denied'):
        repository.page(user_id='user',source_session_id=other.id)
    with pytest.raises(AuditReadError,match='access_denied'):
        repository.page(user_id='other',source_session_id=other.id,project_id='project')
    project=repository.page(user_id='user',source_session_id=source.id,project_id='project')
    assert len(project.events)==1 and project.events[0]['event_kind']=='release.published'
    with sqlite3.connect(path) as db:db.execute("UPDATE projects SET user_id='other' WHERE id='project'")
    with pytest.raises(AuditReadError,match='access_denied'):
        repository.page(user_id='user',source_session_id=source.id,project_id='project',upper=project.upper)
    access.revoke_console_session(user_id='user',session_id=source.id)
    with pytest.raises(AuditReadError,match='access_denied'):
        repository.page(user_id='user',source_session_id=source.id,upper=own.upper)


@pytest.mark.parametrize('options',[{'limit':0},{'limit':101},{'limit':True},{'after':-1},
    {'after':True},{'upper':-1},{'after':2,'upper':1},{'upper':2**63},{'project_id':'../other'}])
def test_invalid_read_scope_and_bounds_denied(reader,options):
    _,repository,_,source,_=reader
    with pytest.raises(AuditReadError):repository.page(user_id='user',source_session_id=source.id,**options)


def test_expired_source_and_schema_drift_fail_closed(reader,monkeypatch):
    path,repository,_,source,_=reader
    monkeypatch.setattr('app.audit_repository.time.time',lambda:160)
    with pytest.raises(AuditReadError,match='access_denied'):
        repository.page(user_id='user',source_session_id=source.id)
    with sqlite3.connect(path) as db:db.execute('CREATE TABLE unexpected(id INTEGER)')
    with pytest.raises(AuditReadError,match='audit_unavailable'):
        repository.page(user_id='user',source_session_id=source.id)


def test_read_has_no_database_effects(reader):
    path,repository,_,source,_=reader
    with sqlite3.connect(path) as db:before=list(db.iterdump())
    repository.page(user_id='user',source_session_id=source.id)
    repository.page(user_id='user',source_session_id=source.id,project_id='project')
    with sqlite3.connect(path) as db:assert list(db.iterdump())==before
