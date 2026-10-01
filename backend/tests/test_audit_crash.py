"""Abrupt process loss around actual audited business transaction commits."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

pytestmark = pytest.mark.parametrize('audit_schema_version', [5, 6, 7])
from app.access_repository import AccessRepository
from app.content_access import ContentAccessRepository
from app.migrations import migrate, verify
from app.release_repository import ReleaseRepository
from test_release_repository import release, ledger, legacy

TABLES=('console_sessions','content_bootstraps','content_handoffs','content_sessions',
        'release_records','release_publications','content_bindings','command_receipts','security_audit_events')


def snapshot(path):
    with sqlite3.connect(path) as db:
        return {name:db.execute('SELECT * FROM '+name+' ORDER BY 1').fetchall() for name in TABLES}


CHILD = r"""
import json,os,sys
from pathlib import Path
from contextlib import contextmanager
from app.access_repository import AccessRepository
from app.content_access import ContentAccessRepository
from app.release_repository import ReleaseRepository
from app.verification_repository import VerificationRepository
p=json.loads(sys.stdin.buffer.read())
owner=VerificationRepository if p['operation'] in ('publish','unpublish') else AccessRepository
original=owner._transaction
@contextmanager
def crash(self):
    with original(self) as db:
        yield db
        if p['phase']=='before':os._exit(71)
    os._exit(72)
owner._transaction=crash
path=Path(p['path'])
if p['operation']=='create':AccessRepository(path).create_console_session(user_id='user',lifetime_seconds=300)
elif p['operation']=='single':AccessRepository(path).revoke_console_session(user_id='user',session_id=p['source'])
elif p['operation']=='account':AccessRepository(path).revoke_console_sessions(user_id='user',source_session_id=p['source'])
elif p['operation']=='issue':ContentAccessRepository(path).issue_handoff(viewer_id='user',source_session_id=p['source'],binding_id=p['binding'],challenge=p['challenge'])
elif p['operation']=='exchange':ContentAccessRepository(path).exchange(binding_id=p['binding'],handoff=p['handoff'],browser_nonce=p['nonce'])
elif p['operation']=='publish':ReleaseRepository(path).publish(**p['publish'])
else:ReleaseRepository(path).unpublish(owner='user',project_id='project',command_id='stop',expected_release='release',expected_generation=1)
raise AssertionError('exit hook not reached')
"""


@pytest.mark.parametrize('operation',['create','single','account','issue','exchange','publish','unpublish'])
@pytest.mark.parametrize('phase',['before','after'])
def test_process_crash_keeps_business_and_audit_atomic(release,tmp_path,operation,phase,audit_schema_version):
    path,_,args=release
    migrate(path,tmp_path/'before-audit.db',target_version=audit_schema_version)
    releases=ReleaseRepository(path)
    releases.publish(**args)
    access=ContentAccessRepository(path)
    source=access.create_console_session(user_id='user',lifetime_seconds=300)
    access.create_console_session(user_id='user',lifetime_seconds=300)
    with sqlite3.connect(path) as db:binding=db.execute('SELECT id FROM content_bindings').fetchone()[0]
    bootstrap=access.bootstrap(binding_id=binding)
    handoff=access.issue_handoff(viewer_id='user',source_session_id=source.id,binding_id=binding,challenge=bootstrap.challenge) if operation=='exchange' else None
    before=snapshot(path)
    payload=dict(path=str(path),operation=operation,phase=phase,source=source.id,binding=binding,
        challenge=bootstrap.challenge,nonce=bootstrap.secret,handoff=handoff.secret if handoff else None,
        publish=args|{'release_id':'second','expected_generation':1})
    result=subprocess.run([sys.executable,'-c',CHILD],input=json.dumps(payload).encode(),capture_output=True,
        cwd=Path(__file__).resolve().parents[1],timeout=15)
    assert result.returncode==(71 if phase=='before' else 72)
    assert not result.stdout and not result.stderr
    assert verify(path)==audit_schema_version
    after=snapshot(path)
    if phase=='before':
        assert after==before
        return
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA integrity_check').fetchall()==[('ok',)]
        assert len(after['security_audit_events'])==len(before['security_audit_events'])+1
        event=db.execute('SELECT event_kind,source_session_id,release_id,affected_count FROM security_audit_events ORDER BY sequence DESC LIMIT 1').fetchone()
        expected={'create':'console.session.created','single':'console.session.revoked','account':'console.account_sessions.revoked',
            'issue':'content.handoff.issued','exchange':'content.session.created','publish':'release.published','unpublish':'release.unpublished'}
        assert event[0]==expected[operation]
        if operation=='create':
            assert len(after['console_sessions'])==len(before['console_sessions'])+1
            assert db.execute('SELECT revoked_at FROM console_sessions WHERE id=?',(event[1],)).fetchone()==(None,)
        elif operation in ('single','account'):
            count=db.execute('SELECT count(*) FROM console_sessions WHERE revoked_at IS NOT NULL').fetchone()[0]
            assert count==event[3]==(1 if operation=='single' else 2)
        elif operation=='issue':assert len(after['content_handoffs'])==len(before['content_handoffs'])+1
        elif operation=='exchange':
            assert len(after['content_sessions'])==len(before['content_sessions'])+1
            assert db.execute('SELECT consumed_at FROM content_bootstraps').fetchone()[0] is not None
            assert db.execute('SELECT consumed_at FROM content_handoffs').fetchone()[0] is not None
        elif operation=='publish':
            assert event[2]=='second'
            assert db.execute('SELECT release_id,generation,live FROM release_publications').fetchone()==('second',2,1)
            assert len(after['command_receipts'])==len(before['command_receipts'])+1
            assert len(after['content_bindings'])==len(before['content_bindings'])+1
        else:
            assert event[2]=='release'
            assert db.execute('SELECT release_id,generation,live FROM release_publications').fetchone()==('release',2,0)
            assert len(after['command_receipts'])==len(before['command_receipts'])+1
