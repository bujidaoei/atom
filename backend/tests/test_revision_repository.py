from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import os
import subprocess
import sys
import threading
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.artifacts import Artifact
from app.migrations import migrate
from app.models import Base, User, Project, Run, Race, RaceHeat
from app.revisions import RevisionRepository, RevisionError


# Repository-only descriptors: physical storage is exercised by Linux integration.
BASE = Artifact('a'*64, 'b'*64, 14)
OUTPUT = Artifact('c'*64, 'd'*64, 15)


@pytest.fixture
def repository(tmp_path):
    path = tmp_path / 'api.db'
    engine = create_engine('sqlite:///' + path.as_posix())
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(User(id='owner', email='owner@example.invalid', name='Owner', password_hash='fixture'))
        s.flush()
        s.add(Project(id='p', user_id='owner', prompt='fixture', title='Fixture', active_run_id='run'))
        s.flush()
        s.add(Run(id='run', project_id='p', role='alex', model='fixture', status='running'))
        s.add(Race(id='race', project_id='p'))
        s.flush()
        s.add(RaceHeat(id='heat', race_id='race', model='fixture', run_id='heat-run'))
        s.add(Run(id='heat-run', project_id='p', heat_id='heat', role='alex', model='fixture', status='running'))
        s.commit()
    engine.dispose()
    migrate(path, tmp_path / 'backup.db')
    with sqlite3.connect(path) as db:
        main = db.execute('SELECT id FROM revision_workspaces WHERE heat_id IS NULL').fetchone()[0]
        heat = db.execute('SELECT id FROM revision_workspaces WHERE heat_id IS NOT NULL').fetchone()[0]
    return RevisionRepository(path), path, main, heat


def allocate(repo, workspace, *, attempt='attempt', run='run', deadline=None):
    return repo.allocate('owner', workspace, run, attempt, 'broker-' + attempt, 'grant-' + attempt,
                         deadline or int(time.time()) + 120)


def register(repo, attempt='attempt', artifact=OUTPUT, owner='owner'):
    return repo.register(owner, attempt, 'broker-' + attempt, 'grant-' + attempt, artifact)


def test_bootstrap_requires_owner_and_is_exactly_idempotent(repository):
    repo, path, main, heat = repository
    with pytest.raises(RevisionError, match='revision_not_found'):
        repo.bootstrap('stranger', main, BASE)
    root = repo.bootstrap('owner', main, BASE)
    assert repo.bootstrap('owner', main, BASE) == root
    with pytest.raises(RevisionError, match='revision_conflict'):
        repo.bootstrap('owner', main, OUTPUT)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT current_revision_id FROM revision_workspaces WHERE id=?', (heat,)).fetchone() == (None,)
        assert db.execute('SELECT COUNT(*) FROM revision_outbox').fetchone() == (0,)


def test_allocation_replay_and_unknown_termination_block_replacement(repository):
    repo, path, main, heat = repository
    with pytest.raises(RevisionError, match='revision_conflict'):
        allocate(repo, main)
    root = repo.bootstrap('owner', main, BASE)
    deadline = int(time.time()) + 120
    first = allocate(repo, main, deadline=deadline)
    assert first.generation == 1 and first.base_revision_id == root
    assert allocate(repo, main, deadline=deadline) == first
    with pytest.raises(RevisionError, match='revision_conflict'):
        allocate(repo, main, deadline=deadline + 1)
    repo.observe_termination('owner', 'attempt', confirmed=False, outcome='failed')
    with pytest.raises(RevisionError, match='revision_conflict'):
        allocate(repo, main, attempt='next')
    repo.observe_termination('owner', 'attempt', confirmed=True, outcome='failed')
    assert allocate(repo, main, attempt='next').generation == 2
    with pytest.raises(RevisionError, match='revision_conflict'):
        register(repo)


def test_commit_receipt_and_outbox_are_atomic_and_replay_survives_successor(repository):
    repo, path, main, heat = repository
    root = repo.bootstrap('owner', main, BASE)
    allocate(repo, main)
    receipt = register(repo)
    assert register(repo) == receipt
    with pytest.raises(RevisionError, match='revision_conflict'):
        register(repo, artifact=BASE)
    with pytest.raises(RevisionError, match='revision_not_found'):
        register(repo, owner='stranger')
    repo.observe_termination('owner', 'attempt', confirmed=True, outcome='succeeded')
    allocate(repo, main, attempt='next')
    assert register(repo) == receipt
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT current_revision_id FROM revision_workspaces WHERE id=?',(main,)).fetchone() == (receipt.revision_id,)
        assert db.execute('SELECT parent_revision_id FROM revision_records WHERE id=?',(receipt.revision_id,)).fetchone() == (root,)
        assert db.execute('SELECT COUNT(*) FROM revision_outbox').fetchone() == (1,)


@pytest.mark.parametrize('point', ['before_commit', 'after_commit'])
def test_abrupt_exit_recovers_commit_or_preserves_old_head(repository, point):
    repo, path, main, heat = repository
    root = repo.bootstrap('owner', main, BASE)
    allocate(repo, main)
    script = '''
import os,sys
from pathlib import Path
from app.artifacts import Artifact
from app.revisions import RevisionRepository
r=RevisionRepository(Path(sys.argv[1]))
if sys.argv[2]=='before_commit':
    original=r._insert_outbox
    def crash(*args):
        original(*args)
        os._exit(43)
    r._insert_outbox=crash
r.register('owner','attempt','broker-attempt','grant-attempt',Artifact('c'*64,'d'*64,15))
os._exit(43)
'''
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    result = subprocess.run([sys.executable,'-c',script,str(path),point], env=env, capture_output=True, timeout=30)
    assert result.returncode == 43, result.stderr
    restarted = RevisionRepository(path)
    receipt = restarted.receipt('owner','attempt','broker-attempt','grant-attempt')
    if point == 'before_commit':
        assert receipt is None
        with sqlite3.connect(path) as db:
            assert db.execute('SELECT current_revision_id FROM revision_workspaces WHERE id=?',(main,)).fetchone() == (root,)
            assert db.execute('SELECT COUNT(*) FROM revision_outbox').fetchone() == (0,)
    else:
        assert receipt == register(restarted)
    assert register(restarted).revision_id != root


def test_failure_after_registration_preserves_revision_without_claiming_success(repository):
    repo, path, main, heat = repository
    repo.bootstrap('owner', main, BASE)
    allocate(repo, main)
    with pytest.raises(RevisionError, match='revision_conflict'):
        repo.observe_termination('owner','attempt',confirmed=True,outcome='succeeded')
    receipt = register(repo)
    repo.cancel('owner','attempt')
    repo.observe_termination('owner','attempt',confirmed=False,outcome='failed')
    repo.observe_termination('owner','attempt',confirmed=True,outcome='failed')
    assert repo.receipt('owner','attempt','broker-attempt','grant-attempt') == receipt
    assert allocate(repo, main, attempt='next').base_revision_id == receipt.revision_id
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT outcome FROM revision_attempts WHERE id='attempt'").fetchone() == ('failed',)


def test_expiry_during_commit_rolls_back_and_busy_writer_is_bounded(repository, monkeypatch):
    repo, path, main, heat = repository
    repo.bootstrap('owner', main, BASE)
    attempt = allocate(repo, main)
    original = repo._insert_outbox
    def expire(*args):
        original(*args)
        monkeypatch.setattr('app.revisions.time.time', lambda: attempt.deadline)
    monkeypatch.setattr(repo, '_insert_outbox', expire)
    with pytest.raises(RevisionError, match='revision_conflict'):
        register(repo)
    assert repo.receipt('owner','attempt','broker-attempt','grant-attempt') is None
    with sqlite3.connect(path) as writer:
        writer.execute('BEGIN IMMEDIATE')
        bounded = RevisionRepository(path, lock_timeout=0.05)
        started = time.monotonic()
        with pytest.raises(RevisionError, match='revision_unavailable'):
            bounded.cancel('owner','attempt')
        assert time.monotonic() - started < 2
        writer.rollback()
        assert not writer.execute('PRAGMA foreign_key_check').fetchall()


@pytest.mark.parametrize('reason', ['cancel', 'expiry', 'new_run', 'run_finished', 'binding'])
def test_stale_execution_cannot_advance_head(repository, monkeypatch, reason):
    repo, path, main, heat = repository
    root = repo.bootstrap('owner', main, BASE)
    attempt = allocate(repo, main)
    if reason == 'cancel':
        repo.cancel('owner', 'attempt')
    elif reason == 'expiry':
        monkeypatch.setattr('app.revisions.time.time', lambda: attempt.deadline)
    elif reason in ('new_run', 'run_finished'):
        with sqlite3.connect(path) as db:
            db.execute("UPDATE projects SET active_run_id=NULL" if reason == 'new_run' else "UPDATE runs SET status='failed'")
    with pytest.raises(RevisionError, match='revision_conflict'):
        if reason == 'binding':
            repo.register('owner','attempt','other','grant-attempt',OUTPUT)
        else:
            register(repo)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT current_revision_id FROM revision_workspaces WHERE id=?',(main,)).fetchone() == (root,)
        assert db.execute('SELECT COUNT(*) FROM revision_receipts').fetchone() == (0,)


def test_heat_output_cannot_change_main_head(repository):
    repo, path, main, heat = repository
    root = repo.bootstrap('owner', main, BASE)
    repo.bootstrap('owner', heat, BASE)
    with pytest.raises(RevisionError, match='revision_conflict'):
        allocate(repo, heat)
    allocate(repo, heat, run='heat-run')
    receipt = register(repo)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT current_revision_id FROM revision_workspaces WHERE id=?',(main,)).fetchone() == (root,)
        assert db.execute('SELECT current_revision_id FROM revision_workspaces WHERE id=?',(heat,)).fetchone() == (receipt.revision_id,)


def test_outbox_failure_rolls_back_entire_commit(repository, monkeypatch):
    repo, path, main, heat = repository
    root = repo.bootstrap('owner', main, BASE)
    allocate(repo, main)
    original = repo._insert_outbox
    def fail(*args):
        original(*args)
        raise sqlite3.OperationalError('injected transaction failure')
    monkeypatch.setattr(repo, '_insert_outbox', fail)
    with pytest.raises(RevisionError, match='revision_unavailable'):
        register(repo)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT COUNT(*) FROM revision_records').fetchone() == (1,)
        assert db.execute('SELECT COUNT(*) FROM revision_artifacts').fetchone() == (1,)
        assert db.execute('SELECT COUNT(*) FROM revision_receipts').fetchone() == (0,)
        assert db.execute('SELECT COUNT(*) FROM revision_outbox').fetchone() == (0,)
        assert db.execute('SELECT current_revision_id FROM revision_workspaces WHERE id=?',(main,)).fetchone() == (root,)
    monkeypatch.setattr(repo, '_insert_outbox', original)
    assert register(repo).revision_id != root


def test_concurrent_duplicate_commit_creates_one_revision(repository):
    repo, path, main, heat = repository
    repo.bootstrap('owner', main, BASE)
    allocate(repo, main)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: register(repo), range(4)))
    assert all(item == results[0] for item in results)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT COUNT(*) FROM revision_records').fetchone() == (2,)
        assert db.execute('SELECT COUNT(*) FROM revision_outbox').fetchone() == (1,)


def test_cancel_commit_race_has_one_durable_order_and_old_cancel_preserves_successor(repository):
    repo, path, main, heat = repository
    repo.bootstrap('owner', main, BASE)
    for number in range(5):
        attempt_id = 'attempt-' + str(number)
        allocate(repo, main, attempt=attempt_id)
        barrier = threading.Barrier(2)
        def commit():
            barrier.wait(timeout=5)
            try:
                return register(repo, attempt=attempt_id)
            except RevisionError as error:
                assert error.code == 'revision_conflict'
                return None
        def cancel():
            barrier.wait(timeout=5)
            repo.cancel('owner', attempt_id)
        with ThreadPoolExecutor(max_workers=2) as pool:
            committed, cancelled = pool.submit(commit), pool.submit(cancel)
            result = committed.result(timeout=10)
            cancelled.result(timeout=10)
        receipt = repo.receipt('owner', attempt_id, 'broker-' + attempt_id, 'grant-' + attempt_id)
        assert receipt == result
        repo.observe_termination('owner', attempt_id, confirmed=True, outcome='succeeded' if receipt else 'cancelled')
    successor = allocate(repo, main, attempt='successor')
    repo.cancel('owner', 'attempt-0')
    with pytest.raises(RevisionError, match='revision_not_found'):
        repo.receipt('stranger','attempt-0','broker-attempt-0','grant-attempt-0')
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT active_attempt_id,generation FROM revision_workspaces WHERE id=?',(main,)).fetchone() == ('successor',successor.generation)
