from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import sqlite3
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Barrier

import pytest

from app.access_repository import AccessError
from app.content_access import AccessLimits, ContentAccessRepository
from app.migrations import migrate
from test_content_repository import content, release, ledger, legacy


@pytest.fixture(params=[4,5])
def private(content,tmp_path,monkeypatch,request):
    path,repository,*_=content
    binding=repository.bind(owner='user',project_id='project',release_id='release')
    migrate(path,tmp_path/'v3.db',target_version=request.param)
    monkeypatch.setattr('app.content_access.time.time',lambda:100)
    access=ContentAccessRepository(path)
    source=access.create_console_session(user_id='user',lifetime_seconds=1000)
    return path,access,binding.id,source


def issue(private):
    _,access,binding,source=private
    bootstrap=access.bootstrap(binding_id=binding)
    handoff=access.issue_handoff(viewer_id='user',source_session_id=source.id,binding_id=binding,challenge=bootstrap.challenge)
    return bootstrap,handoff


def test_complete_exchange_stores_only_hashes_and_rejects_replay(private):
    path,access,binding,source=private
    bootstrap,handoff=issue(private)
    session=access.exchange(binding_id=binding,handoff=handoff.secret,browser_nonce=bootstrap.secret)
    principal=ContentAccessRepository(path).authorize(binding_id=binding,session_secret=session.secret)
    assert principal.viewer_id=='user' and principal.source_session_id==source.id
    assert principal.publication_generation==1 and session.expires_at==1000
    with pytest.raises(AccessError):access.exchange(binding_id=binding,handoff=handoff.secret,browser_nonce=bootstrap.secret)
    with sqlite3.connect(path) as db:
        dump='\n'.join(db.iterdump())
        for secret in (bootstrap.secret,handoff.secret,session.secret):assert secret not in dump
        assert db.execute('SELECT count(*) FROM content_sessions').fetchone()==(1,)
    for credential in (bootstrap,handoff,session):assert credential.secret not in repr(credential)


@pytest.mark.parametrize('changed',[{'browser_nonce':'f'*64},{'binding_id':'f'*32},{'handoff':'f'*64},
    {'browser_nonce':'not-hex'}])
def test_wrong_browser_or_scope_does_not_consume(private,changed):
    _,access,binding,_=private
    bootstrap,handoff=issue(private)
    args=dict(binding_id=binding,handoff=handoff.secret,browser_nonce=bootstrap.secret)
    with pytest.raises(AccessError):access.exchange(**(args|changed))
    assert access.exchange(**args)


def test_concurrent_exchange_has_one_winner(private):
    path,access,binding,_=private
    bootstrap,handoff=issue(private)
    barrier=Barrier(2)
    def redeem(_):
        barrier.wait(timeout=3)
        try:return access.exchange(binding_id=binding,handoff=handoff.secret,browser_nonce=bootstrap.secret)
        except AccessError as error:
            assert str(error)=='content_access_denied'
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(redeem,range(2)))
    assert sum(result is not None for result in results)==1
    with sqlite3.connect(path) as db:assert db.execute('SELECT count(*) FROM content_sessions').fetchone()==(1,)


@pytest.mark.parametrize('when',['before_exchange','after_exchange'])
@pytest.mark.parametrize('change',['logout','generation','offline'])
def test_revocation_or_publication_change_denies_access(private,when,change):
    path,access,binding,source=private
    bootstrap,handoff=issue(private)
    if when=='after_exchange':
        session=access.exchange(binding_id=binding,handoff=handoff.secret,browser_nonce=bootstrap.secret)
    if change=='logout':access.revoke_console_session(user_id='user',session_id=source.id)
    else:
        # Fixture control-plane mutation: serving repositories are not on v4 yet.
        with sqlite3.connect(path) as db:
            db.execute('UPDATE release_publications SET '+('generation=generation+1' if change=='generation' else 'live=0'))
    with pytest.raises(AccessError):
        if when=='after_exchange':access.authorize(binding_id=binding,session_secret=session.secret)
        else:access.exchange(binding_id=binding,handoff=handoff.secret,browser_nonce=bootstrap.secret)


def test_late_session_insert_failure_rolls_back_both_consumptions(private,monkeypatch):
    path,access,binding,_=private
    bootstrap,handoff=issue(private)
    original=access._transaction
    @contextmanager
    def fail():
        with original() as db:
            db.set_authorizer(lambda action,table,*_:sqlite3.SQLITE_DENY
                if action==sqlite3.SQLITE_INSERT and table=='content_sessions' else sqlite3.SQLITE_OK)
            yield db
    monkeypatch.setattr(access,'_transaction',fail)
    with pytest.raises(AccessError):access.exchange(binding_id=binding,handoff=handoff.secret,browser_nonce=bootstrap.secret)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT consumed_at FROM content_bootstraps').fetchone()==(None,)
        assert db.execute('SELECT consumed_at FROM content_handoffs').fetchone()==(None,)
        assert db.execute('SELECT count(*) FROM content_sessions').fetchone()==(0,)
    assert ContentAccessRepository(path).exchange(binding_id=binding,handoff=handoff.secret,browser_nonce=bootstrap.secret)


@pytest.mark.parametrize('now',[99,220])
def test_exchange_clock_boundaries(private,monkeypatch,now):
    _,access,binding,_=private
    bootstrap,handoff=issue(private)
    monkeypatch.setattr('app.content_access.time.time',lambda:now)
    with pytest.raises(AccessError):access.exchange(binding_id=binding,handoff=handoff.secret,browser_nonce=bootstrap.secret)


def test_pending_and_active_capacities_do_not_consume_denied_attempt(private):
    path,_,binding,source=private
    access=ContentAccessRepository(path,limits=AccessLimits(pending_per_binding=1,sessions_per_viewer_binding=1))
    bootstrap=access.bootstrap(binding_id=binding)
    with pytest.raises(AccessError,match='content_access_capacity'):access.bootstrap(binding_id=binding)
    handoff=access.issue_handoff(viewer_id='user',source_session_id=source.id,binding_id=binding,challenge=bootstrap.challenge)
    first=access.exchange(binding_id=binding,handoff=handoff.secret,browser_nonce=bootstrap.secret)
    bootstrap=access.bootstrap(binding_id=binding)
    handoff=access.issue_handoff(viewer_id='user',source_session_id=source.id,binding_id=binding,challenge=bootstrap.challenge)
    with pytest.raises(AccessError,match='content_access_capacity'):
        access.exchange(binding_id=binding,handoff=handoff.secret,browser_nonce=bootstrap.secret)
    assert access.authorize(binding_id=binding,session_secret=first.secret)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM content_handoffs WHERE consumed_at IS NULL').fetchone()==(1,)


def test_session_collision_rolls_back_consumption(private,monkeypatch):
    path,access,binding,_=private
    bootstrap,handoff=issue(private)
    first=access.exchange(binding_id=binding,handoff=handoff.secret,browser_nonce=bootstrap.secret)
    bootstrap,handoff=issue(private)
    monkeypatch.setattr('app.content_access.secrets.token_hex',lambda _:first.secret)
    with pytest.raises(AccessError,match='access_conflict'):
        access.exchange(binding_id=binding,handoff=handoff.secret,browser_nonce=bootstrap.secret)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM content_handoffs WHERE consumed_at IS NULL').fetchone()==(1,)
        assert db.execute('SELECT count(*) FROM content_sessions').fetchone()==(1,)
    assert access.authorize(binding_id=binding,session_secret=first.secret)


def test_foreign_issuer_and_repeated_issue_do_not_replace_handoff(private):
    path,access,binding,source=private
    bootstrap=access.bootstrap(binding_id=binding)
    with pytest.raises(AccessError):
        access.issue_handoff(viewer_id='foreign',source_session_id=source.id,binding_id=binding,challenge=bootstrap.challenge)
    handoff=access.issue_handoff(viewer_id='user',source_session_id=source.id,binding_id=binding,challenge=bootstrap.challenge)
    with pytest.raises(AccessError,match='access_conflict'):
        access.issue_handoff(viewer_id='user',source_session_id=source.id,binding_id=binding,challenge=bootstrap.challenge)
    assert access.exchange(binding_id=binding,handoff=handoff.secret,browser_nonce=bootstrap.secret)


def test_process_exit_before_exchange_commit_preserves_retry(private):
    path,access,binding,_=private
    bootstrap,handoff=issue(private)
    args=dict(binding_id=binding,handoff=handoff.secret,browser_nonce=bootstrap.secret)
    script='''
import json,os,sys
from contextlib import contextmanager
from pathlib import Path
import app.content_access as module
module.time.time=lambda:100
source=json.loads(sys.stdin.read())
repository=module.ContentAccessRepository(Path(source['path']))
original=repository._transaction
@contextmanager
def crash():
    with original() as db:
        yield db
        os._exit(46)
repository._transaction=crash
repository.exchange(**source['args'])
'''
    result=subprocess.run([sys.executable,'-c',script],input=json.dumps({'path':str(path),'args':args}),
        text=True,capture_output=True,timeout=15,
        env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1])))
    assert result.returncode==46,result.stderr
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT consumed_at FROM content_handoffs').fetchone()==(None,)
        assert db.execute('SELECT consumed_at FROM content_bootstraps').fetchone()==(None,)
        assert db.execute('SELECT count(*) FROM content_sessions').fetchone()==(0,)
    assert access.exchange(**args)


def test_account_revoke_denies_live_content_and_pending_handoff(private):
    _,access,binding,source=private
    first_bootstrap,first_handoff=issue(private)
    content=access.exchange(binding_id=binding,handoff=first_handoff.secret,browser_nonce=first_bootstrap.secret)
    second=access.create_console_session(user_id='user',lifetime_seconds=1000)
    bootstrap=access.bootstrap(binding_id=binding)
    pending=access.issue_handoff(viewer_id='user',source_session_id=second.id,binding_id=binding,challenge=bootstrap.challenge)
    assert access.revoke_console_sessions(user_id='user',source_session_id=source.id)==2
    with pytest.raises(AccessError):access.authorize(binding_id=binding,session_secret=content.secret)
    with pytest.raises(AccessError):access.exchange(binding_id=binding,handoff=pending.secret,browser_nonce=bootstrap.secret)
