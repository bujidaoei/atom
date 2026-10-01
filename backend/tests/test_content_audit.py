import sqlite3
from contextlib import contextmanager

import pytest
from app.access_repository import AccessError
from app.content_access import ContentAccessRepository, _hash
from app.migrations import migrate
from test_content_repository import content, release, ledger, legacy


@pytest.fixture
def audited_content(content,tmp_path,monkeypatch):
    path,repository,*_=content
    binding=repository.bind(owner='user',project_id='project',release_id='release')
    migrate(path,tmp_path/'before-audit.db',target_version=5)
    monkeypatch.setattr('app.content_access.time.time',lambda:100)
    access=ContentAccessRepository(path)
    source=access.create_console_session(user_id='user',lifetime_seconds=1000)
    bootstrap=access.bootstrap(binding_id=binding.id)
    return path,access,binding.id,source,bootstrap


def state(path):
    with sqlite3.connect(path) as db:
        return {table:db.execute('SELECT * FROM '+table+' ORDER BY 1').fetchall() for table in
            ('content_bootstraps','content_handoffs','content_sessions','security_audit_events')}


def test_scope_provenance_and_no_credential_material(audited_content):
    path,access,binding,source,bootstrap=audited_content
    before=state(path)
    access.describe_handoff(viewer_id='user',source_session_id=source.id,binding_id=binding,challenge=bootstrap.challenge)
    assert state(path)==before
    handoff=access.issue_handoff(viewer_id='user',source_session_id=source.id,binding_id=binding,challenge=bootstrap.challenge)
    session=access.exchange(binding_id=binding,handoff=handoff.secret,browser_nonce=bootstrap.secret)
    with sqlite3.connect(path) as db:
        rows=db.execute("SELECT event_kind,scope_kind,scope_id,binding_id,release_id,revision_id,publication_generation FROM security_audit_events WHERE event_kind LIKE 'content.%' ORDER BY sequence").fetchall()
        revision=db.execute("SELECT revision_id FROM release_records WHERE id='release'").fetchone()[0]
        raw=repr(db.execute('SELECT * FROM security_audit_events').fetchall())
    assert rows==[(kind,'project','project',binding,'release',revision,1)
        for kind in ('content.handoff.issued','content.session.created')]
    for value in (bootstrap.secret,bootstrap.challenge,handoff.secret,session.secret,
                  _hash('handoff',handoff.secret),_hash('session',session.secret)):
        assert value not in raw
    before=state(path)
    with pytest.raises(AccessError):access.exchange(binding_id=binding,handoff=handoff.secret,browser_nonce=bootstrap.secret)
    assert state(path)==before


@pytest.mark.parametrize('operation',['issue','exchange'])
@pytest.mark.parametrize('failure',['insert','after'])
def test_audit_failure_rolls_back_credential_and_consumption(audited_content,monkeypatch,operation,failure):
    path,access,binding,source,bootstrap=audited_content
    handoff=None
    if operation=='exchange':
        handoff=access.issue_handoff(viewer_id='user',source_session_id=source.id,binding_id=binding,challenge=bootstrap.challenge)
    before=state(path)
    original=access._transaction
    @contextmanager
    def failing():
        with original() as db:
            if failure=='insert':
                db.set_authorizer(lambda action,table,*_:sqlite3.SQLITE_DENY
                    if action==sqlite3.SQLITE_INSERT and table=='security_audit_events' else sqlite3.SQLITE_OK)
            yield db
            if failure=='after':raise sqlite3.OperationalError('test_late_audit_failure')
    monkeypatch.setattr(access,'_transaction',failing)
    with pytest.raises(AccessError):
        if operation=='issue':access.issue_handoff(viewer_id='user',source_session_id=source.id,binding_id=binding,challenge=bootstrap.challenge)
        else:access.exchange(binding_id=binding,handoff=handoff.secret,browser_nonce=bootstrap.secret)
    assert state(path)==before
    monkeypatch.setattr(access,'_transaction',original)
    if handoff is None:
        handoff=access.issue_handoff(viewer_id='user',source_session_id=source.id,binding_id=binding,challenge=bootstrap.challenge)
    assert access.exchange(binding_id=binding,handoff=handoff.secret,browser_nonce=bootstrap.secret)
