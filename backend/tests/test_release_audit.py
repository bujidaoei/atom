import sqlite3
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

pytestmark = pytest.mark.parametrize('audit_schema_version', [5, 6])
from app.migrations import migrate
from app.release_repository import ReleaseRepository
from app.verification_repository import VerificationError
from test_release_repository import release, ledger, legacy


@pytest.fixture
def audited_release(release,tmp_path,audit_schema_version):
    path,_,args=release
    migrate(path,tmp_path/'before-release-audit.db',target_version=audit_schema_version)
    return path,ReleaseRepository(path),args


def state(path):
    with sqlite3.connect(path) as db:
        return {table:db.execute('SELECT * FROM '+table+' ORDER BY 1').fetchall() for table in
            ('release_records','release_publications','content_bindings','command_receipts','security_audit_events')}


def test_publish_unpublish_events_match_receipts_and_replay(audited_release):
    path,repository,args=audited_release
    first=repository.publish(**args)
    assert repository.publish(**args)==first
    command=dict(owner='user',project_id='project',command_id='stop',expected_release='release',expected_generation=1)
    stopped=repository.unpublish(**command)
    assert repository.unpublish(**command)==stopped
    assert repository.publish(**args)==first
    with sqlite3.connect(path) as db:
        binding=db.execute('SELECT id FROM content_bindings').fetchone()[0]
        rows=db.execute('SELECT event_kind,actor_id,scope_id,operation_id,binding_id,release_id,revision_id,publication_generation FROM security_audit_events ORDER BY sequence').fetchall()
        assert rows==[
            ('release.published','user','project','release',binding,'release','root',1),
            ('release.unpublished','user','project','stop',binding,'release','root',2)]
        assert db.execute('SELECT live,generation FROM release_publications').fetchone()==(0,2)


@pytest.mark.parametrize('operation',['publish','unpublish'])
@pytest.mark.parametrize('failure',['insert','after'])
def test_failed_audit_preserves_entire_previous_publication(audited_release,monkeypatch,operation,failure):
    path,repository,args=audited_release
    repository.publish(**args)
    before=state(path)
    original=repository._ledger._transaction
    @contextmanager
    def failing():
        with original() as db:
            if failure=='insert':
                db.set_authorizer(lambda action,table,*_:sqlite3.SQLITE_DENY
                    if action==sqlite3.SQLITE_INSERT and table=='security_audit_events' else sqlite3.SQLITE_OK)
            yield db
            if failure=='after':raise sqlite3.OperationalError('test_late_failure')
    monkeypatch.setattr(repository._ledger,'_transaction',failing)
    with pytest.raises(VerificationError):
        if operation=='publish':repository.publish(**(args|{'release_id':'second','expected_generation':1}))
        else:repository.unpublish(owner='user',project_id='project',command_id='stop',expected_release='release',expected_generation=1)
    assert state(path)==before


def test_competing_publications_emit_only_winning_transition(audited_release):
    path,repository,args=audited_release
    barrier=Barrier(2)
    def publish(name):
        barrier.wait(timeout=3)
        try:return repository.publish(**(args|{'release_id':name}))
        except VerificationError:return None
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(publish,['one','two']))
    winner,=[result for result in results if result is not None]
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT release_id FROM security_audit_events').fetchall()==[(winner.release_id,)]
        assert db.execute('SELECT release_id FROM release_publications').fetchone()==(winner.release_id,)


def test_bound_content_resolves_with_current_visibility(audited_release):
    from app.content_repository import ContentRepository
    path,releases,args=audited_release
    releases.publish(**args)
    content=ContentRepository(path)
    binding=content.bind(owner='user',project_id='project',release_id='release')
    assert content.resolve(binding_id=binding.id,viewer='user').revision_id=='root'
    with pytest.raises(VerificationError):
        content.resolve(binding_id=binding.id)
    releases.unpublish(owner='user',project_id='project',command_id='stop',expected_release='release',expected_generation=1)
    with pytest.raises(VerificationError):
        content.resolve(binding_id=binding.id,viewer='user')
