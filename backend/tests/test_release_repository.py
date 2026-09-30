from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import sqlite3
from threading import Barrier

import pytest

from app.release_repository import ReleaseRepository
from app.verification_repository import VerificationError
from test_verification_repository import ledger, legacy, report


@pytest.fixture
def release(ledger):
    path, verification, arguments = ledger
    request = verification.reserve(**arguments)
    verification.record_report(owner='user',request_id=request.id,results=report())
    args = dict(owner='user',project_id='project',release_id='release',verification_id=request.id,
        expected_revision='root',expected_generation=0,policy_digest='c'*64,runner_version='runner-1',
        audience='owner',slug='site')
    return path,ReleaseRepository(path),args


def test_atomic_publish_replay_and_history(release):
    path, repository, args = release
    first = repository.publish(**args)
    second = repository.publish(**(args | {'release_id':'release2','expected_generation':1}))
    assert second.generation == 2
    assert ReleaseRepository(path).publish(**args) == first
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT release_id,generation FROM release_publications').fetchone() == ('release2',2)
        assert db.execute("SELECT previous_release_id FROM release_records WHERE id='release2'").fetchone() == ('release',)
        assert db.execute('SELECT count(*) FROM command_receipts').fetchone() == (2,)
    with pytest.raises(VerificationError, match='release_conflict'):
        repository.publish(**(args | {'audience':'public'}))


@pytest.mark.parametrize('changed', [dict(owner='foreign'),dict(expected_revision='other'),
    dict(policy_digest='d'*64),dict(runner_version='runner-2'),dict(verification_id='missing'),dict(expected_generation=1)])
def test_invalid_publication_preserves_empty_pointer(release,changed):
    path, repository, args = release
    with pytest.raises(VerificationError): repository.publish(**(args | changed))
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM release_publications').fetchone() == (0,)
        assert db.execute('SELECT count(*) FROM release_records').fetchone() == (0,)


def test_changed_contract_cannot_reuse_old_passing_evidence(release):
    path,repository,args = release
    first = repository.publish(**args)
    with sqlite3.connect(path) as db: db.execute("UPDATE requirements SET title='Changed'")
    with pytest.raises(VerificationError,match='release_stale_evidence'):
        repository.publish(**(args | {'release_id':'new','expected_generation':1}))
    assert repository.publish(**args) == first
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT release_id,generation FROM release_publications').fetchone() == ('release',1)


def test_two_publishers_cannot_overwrite_same_generation(release):
    path,repository,args = release
    barrier = Barrier(2)
    def publish(name):
        barrier.wait(timeout=3)
        try: return repository.publish(**(args | {'release_id':name}))
        except VerificationError as error:
            assert str(error) == 'release_conflict'
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(publish,['one','two']))
    assert sum(result is not None for result in results) == 1
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM release_records').fetchone() == (1,)
        assert db.execute('SELECT generation FROM release_publications').fetchone() == (1,)


@pytest.mark.parametrize('operation',['publish','unpublish'])
def test_receipt_write_failure_rolls_back_pointer_and_release(release,monkeypatch,operation):
    path,repository,args = release
    repository.publish(**args)
    original = repository._ledger._transaction
    denied = []
    @contextmanager
    def fail_receipt():
        with original() as db:
            def authorize(action,table,*rest):
                if action == sqlite3.SQLITE_INSERT and table == 'command_receipts':
                    denied.append(table)
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            db.set_authorizer(authorize)
            yield db
    monkeypatch.setattr(repository._ledger,'_transaction',fail_receipt)
    with pytest.raises(VerificationError):
        if operation == 'publish':
            repository.publish(**(args | {'release_id':'new','expected_generation':1}))
        else:
            repository.unpublish(owner='user',project_id='project',command_id='off',expected_release='release',expected_generation=1)
    assert denied == ['command_receipts']
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT id FROM release_records').fetchall() == [('release',)]
        assert db.execute('SELECT release_id,generation FROM release_publications').fetchone() == ('release',1)
        assert db.execute('SELECT live FROM release_publications').fetchone() == (1,)


def test_unpublish_replay_cannot_disable_later_release(release):
    path,repository,args = release
    first = repository.publish(**args)
    command = dict(owner='user',project_id='project',command_id='off',expected_release=first.release_id,expected_generation=1)
    stopped = repository.unpublish(**command)
    assert stopped.generation == 2
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT live,generation FROM release_publications').fetchone() == (0,2)
        assert db.execute('SELECT count(*) FROM release_records').fetchone() == (1,)
    next_release = repository.publish(**(args | {'release_id':'new','expected_generation':2}))
    assert next_release.generation == 3
    assert ReleaseRepository(path).unpublish(**command) == stopped
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT release_id,live,generation FROM release_publications').fetchone() == ('new',1,3)
    with pytest.raises(VerificationError): repository.unpublish(**(command | {'command_id':'stale'}))
    with pytest.raises(VerificationError): repository.unpublish(**(command | {'expected_generation':3}))
    with pytest.raises(VerificationError): repository.unpublish(**(command | {'owner':'foreign'}))


def test_publish_and_unpublish_compete_for_one_generation(release):
    path,repository,args = release
    repository.publish(**args)
    barrier = Barrier(2)
    def run(stop):
        barrier.wait(timeout=3)
        try:
            if stop:
                return repository.unpublish(owner='user',project_id='project',command_id='off',expected_release='release',expected_generation=1)
            return repository.publish(**(args | {'release_id':'new','expected_generation':1}))
        except VerificationError as error:
            assert str(error) == 'release_conflict'
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run,[True,False]))
    assert sum(value is not None for value in results) == 1
    with sqlite3.connect(path) as db:
        current = db.execute('SELECT release_id,live,generation FROM release_publications').fetchone()
        assert current in [('release',0,2),('new',1,2)]
        assert db.execute('SELECT count(*) FROM command_receipts').fetchone() == (2,)
