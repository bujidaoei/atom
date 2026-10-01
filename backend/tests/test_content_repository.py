from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import sqlite3

import pytest

from app.content_repository import ContentRepository
from app.migrations import migrate
from app.release_repository import ReleaseRepository
from app.verification_repository import VerificationError
from test_release_repository import release, ledger, legacy


@pytest.fixture
def content(release,tmp_path):
    path,releases,args=release
    releases.publish(**args)
    migrate(path,tmp_path/'before-content.db',target_version=3)
    return path,ContentRepository(path),ReleaseRepository(path),args


def test_concurrent_binding_is_unique_and_private(content):
    path,repository,releases,args=content
    def bind(_):return repository.bind(owner='user',project_id='project',release_id='release')
    with ThreadPoolExecutor(max_workers=2) as pool:values=list(pool.map(bind,range(2)))
    assert values[0]==values[1] and len(values[0].id)==32
    assert ContentRepository(path).bind(owner='user',project_id='project',release_id='release')==values[0]
    with pytest.raises(VerificationError):repository.resolve(binding_id=values[0].id)
    assert repository.resolve(binding_id=values[0].id,viewer='user').release_id=='release'
    with sqlite3.connect(path) as db:assert db.execute('SELECT count(*) FROM content_bindings').fetchone()==(1,)


def test_bound_history_obeys_current_visibility(content):
    path,repository,releases,args=content
    releases.publish(**(args|{'release_id':'public','expected_generation':1,'audience':'public'}))
    binding=repository.bind(owner='user',project_id='project',release_id='public')
    assert repository.resolve(binding_id=binding.id).release_id=='public'
    releases.unpublish(owner='user',project_id='project',command_id='off',expected_release='public',expected_generation=2)
    with pytest.raises(VerificationError):repository.resolve(binding_id=binding.id,viewer='user')
    releases.publish(**(args|{'release_id':'private','expected_generation':3}))
    with pytest.raises(VerificationError):repository.resolve(binding_id=binding.id)
    assert repository.resolve(binding_id=binding.id,viewer='user').release_id=='public'


def test_foreign_binding_and_collision_have_no_effects(content,monkeypatch):
    path,repository,releases,args=content
    for owner,project in [('foreign','project'),('user','other')]:
        with pytest.raises(VerificationError):repository.bind(owner=owner,project_id=project,release_id='release')
    first=repository.bind(owner='user',project_id='project',release_id='release')
    monkeypatch.setattr('app.content_bindings.secrets.token_hex',lambda _:first.id)
    with pytest.raises(VerificationError,match='verification_conflict'):
        releases.publish(**(args|{'release_id':'next','expected_generation':1}))
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT id,release_id FROM content_bindings').fetchall()==[(first.id,'release')]
        assert db.execute('SELECT release_id,generation FROM release_publications').fetchone()==('release',1)
        assert db.execute("SELECT count(*) FROM release_records WHERE id='next'").fetchone()==(0,)


def test_binding_requires_v3(release):
    path,releases,args=release
    releases.publish(**args)
    with pytest.raises(VerificationError,match='content_schema_required'):
        ContentRepository(path).bind(owner='user',project_id='project',release_id='release')


@pytest.mark.parametrize('identity',['missing','A'*32,'a'*31,'../release','a'*32])
def test_invalid_or_missing_binding_is_denied(content,identity):
    with pytest.raises(VerificationError,match='content_not_found'):
        content[1].resolve(binding_id=identity)


def test_sharing_tracks_only_live_public_bound_release_without_writes(content):
    path,repository,releases,args=content
    with pytest.raises(VerificationError,match='content_not_found'):
        repository.sharing_binding(slug='site')
    public=args|{'release_id':'public','expected_generation':1,'audience':'public'}
    releases.publish(**public)
    first=repository.sharing_binding(slug='site')
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM content_bindings').fetchone()==(1,)
    assert repository.bind(owner='user',project_id='project',release_id='public')==first
    assert repository.sharing_binding(slug='site')==first
    releases.publish(**(public|{'release_id':'new','expected_generation':2}))
    second=repository.sharing_binding(slug='site')
    assert repository.bind(owner='user',project_id='project',release_id='new')==second
    assert repository.sharing_binding(slug='site')==second
    assert repository.resolve(binding_id=first.id).release_id=='public'
    releases.publish(**(args|{'release_id':'private','expected_generation':3}))
    with pytest.raises(VerificationError,match='content_not_found'):
        repository.sharing_binding(slug='site')
    releases.unpublish(owner='user',project_id='project',command_id='off',expected_release='private',expected_generation=4)
    with pytest.raises(VerificationError,match='content_not_found'):
        repository.sharing_binding(slug='site')


def test_migrated_publication_requires_explicit_binding(release,tmp_path):
    path,releases,args=release
    releases.publish(**(args|{'audience':'public'}))
    migrate(path,tmp_path/'v2.db',target_version=3)
    repository=ContentRepository(path)
    with pytest.raises(VerificationError,match='content_binding_unavailable'):
        repository.sharing_binding(slug='site')
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM content_bindings').fetchone()==(0,)
    binding=repository.bind(owner='user',project_id='project',release_id='release')
    assert repository.sharing_binding(slug='site')==binding


@pytest.mark.parametrize('denied_table',['content_bindings','command_receipts'])
def test_v3_publish_failure_preserves_prior_binding_and_pointer(content,monkeypatch,denied_table):
    path,repository,releases,args=content
    first=repository.bind(owner='user',project_id='project',release_id='release')
    original=releases._ledger._transaction
    denied=[]
    @contextmanager
    def failing_transaction():
        with original() as db:
            def authorize(action,table,*_rest):
                if action==sqlite3.SQLITE_INSERT and table==denied_table:
                    denied.append(table)
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            db.set_authorizer(authorize)
            yield db
    monkeypatch.setattr(releases._ledger,'_transaction',failing_transaction)
    with pytest.raises(VerificationError):
        releases.publish(**(args|{'release_id':'failed','expected_generation':1}))
    assert denied
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT id,release_id FROM content_bindings').fetchall()==[(first.id,'release')]
        assert db.execute('SELECT id FROM release_records').fetchall()==[('release',)]
        assert db.execute('SELECT release_id,generation FROM release_publications').fetchone()==('release',1)
        assert db.execute('SELECT count(*) FROM command_receipts').fetchone()==(1,)


def test_v3_competing_publish_and_replay_keep_one_binding(content,monkeypatch):
    from threading import Barrier
    path,repository,releases,args=content
    barrier=Barrier(2)
    def publish(identity):
        barrier.wait(timeout=3)
        try:return releases.publish(**(args|{'release_id':identity,'expected_generation':1,'audience':'public'}))
        except VerificationError as error:
            assert str(error)=='release_conflict'
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts=list(pool.map(publish,['first','second']))
    winners=[receipt for receipt in receipts if receipt is not None]
    assert len(winners)==1
    winner=winners[0]
    binding=repository.sharing_binding(slug='site')
    assert binding.release_id==winner.release_id
    def unexpected_allocation(_):raise AssertionError('replay allocated a new binding')
    monkeypatch.setattr('app.content_bindings.secrets.token_hex',unexpected_allocation)
    replay=args|{'release_id':winner.release_id,'expected_generation':1,'audience':'public'}
    assert releases.publish(**replay)==winner
    releases.unpublish(owner='user',project_id='project',command_id='off',expected_release=winner.release_id,expected_generation=2)
    assert releases.publish(**replay)==winner
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT id,release_id FROM content_bindings').fetchall()==[(binding.id,winner.release_id)]
        assert db.execute('SELECT count(*) FROM release_records').fetchone()==(2,)
        assert db.execute('SELECT generation,live FROM release_publications').fetchone()==(3,0)
