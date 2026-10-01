from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import os
import subprocess
import sys
import threading
import time
import asyncio
import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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


@pytest.fixture(params=[1,4,5,6],ids=["schema-v1","schema-v4","schema-v5","schema-v6"])
def repository(tmp_path,request):
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
    migrate(path, tmp_path / 'backup.db',target_version=request.param)
    with sqlite3.connect(path) as db:
        main = db.execute('SELECT id FROM revision_workspaces WHERE heat_id IS NULL').fetchone()[0]
        heat = db.execute('SELECT id FROM revision_workspaces WHERE heat_id IS NOT NULL').fetchone()[0]
    return RevisionRepository(path), path, main, heat


def allocate(repo, workspace, *, attempt='attempt', run='run', deadline=None):
    repo.reserve('owner', workspace, run, attempt, 'grant-' + attempt, deadline or int(time.time()) + 120)
    return repo.bind('owner',attempt,'broker-' + attempt)


def test_committed_revision_read_is_owner_scoped_and_preserves_captured_identity(repository):
    repo, path, main, heat = repository
    assert repo.current_revision('owner', main) is None
    with pytest.raises(RevisionError, match='revision_not_found'):
        repo.current_revision('foreign', main)
    root=repo.bootstrap('owner', main, BASE)
    captured=repo.current_revision('owner', main)
    assert captured.workspace_id==main and captured.revision_id==root and captured.artifact==BASE
    allocate(repo, main)
    receipt=register(repo)
    current=repo.current_revision('owner', main)
    assert current.revision_id==receipt.revision_id and current.artifact==OUTPUT
    assert captured.revision_id==root and captured.artifact==BASE
    assert repo.current_revision('owner', heat) is None
    assert repo.recovery('owner', 'attempt').state=='active'


def test_startup_inventory_is_bounded_and_keeps_unknown_attempts(repository):
    repo, path, main, heat = repository
    assert repo.pending_executions() == ()
    repo.bootstrap('owner', main, BASE)
    repo.bootstrap('owner', heat, BASE)
    allocate(repo, main)
    allocate(repo, heat, attempt='heat-attempt', run='heat-run')
    repo.cancel('owner', 'attempt')
    repo.observe_termination('owner', 'attempt', confirmed=False, outcome='cancelled')
    assert {item.attempt_id for item in repo.pending_executions()} == {'attempt','heat-attempt'}
    assert {item.owner for item in repo.pending_executions()} == {'owner'}
    with pytest.raises(RevisionError, match='revision_recovery_capacity'):
        repo.pending_executions(limit=1)
    for invalid in (0, True, 1001, '1'):
        with pytest.raises(RevisionError, match='invalid_revision_request'):
            repo.pending_executions(limit=invalid)
    repo.observe_termination('owner', 'attempt', confirmed=True, outcome='cancelled')
    assert [item.attempt_id for item in repo.pending_executions(limit=1)] == ['heat-attempt']


def test_workspace_identity_after_migration_is_concurrent_and_empty(repository):
    repo, path, main, heat = repository
    engine = create_engine('sqlite:///' + path.as_posix())
    with Session(engine) as s:
        s.add(Project(id='new', user_id='owner', prompt='fixture', title='New'))
        s.flush()
        s.add(Race(id='new-race', project_id='new'))
        s.flush()
        s.add(RaceHeat(id='new-heat', race_id='new-race', model='fixture'))
        s.commit()
    engine.dispose()
    for heat_id in (None, 'new-heat'):
        with ThreadPoolExecutor(max_workers=4) as pool:
            identities = list(pool.map(lambda _: repo.ensure_workspace('owner', 'new', heat_id), range(8)))
        assert len(set(identities)) == 1
        with sqlite3.connect(path) as db:
            row = db.execute('SELECT project_id,heat_id,current_revision_id,generation,active_attempt_id '
                             'FROM revision_workspaces WHERE id=?', (identities[0],)).fetchone()
            assert row == ('new', heat_id, None, 0, None)
            assert db.execute('SELECT count(*) FROM revision_records').fetchone()[0] == 0
            assert db.execute('SELECT count(*) FROM revision_artifacts').fetchone()[0] == 0


def test_workspace_identity_replay_preserves_active_head(repository):
    repo, path, main, heat = repository
    root = repo.bootstrap('owner', main, BASE)
    attempt = allocate(repo, main)
    assert repo.ensure_workspace('owner', 'p') == main
    assert repo.ensure_workspace('owner', 'p', 'heat') == heat
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT current_revision_id,generation,active_attempt_id FROM revision_workspaces '
                          'WHERE id=?', (main,)).fetchone() == (root, attempt.generation, attempt.id)


@pytest.mark.parametrize('owner,project,heat', [
    ('foreign', 'p', None), ('owner', 'missing', None), ('owner', 'p', 'missing'),
    ('owner', 'p', ''), ('owner', '../p', None),
])
def test_workspace_identity_denies_invalid_scope_without_effects(repository, owner, project, heat):
    repo, path, main, existing_heat = repository
    with sqlite3.connect(path) as db:
        before = db.execute('SELECT * FROM revision_workspaces ORDER BY id').fetchall()
    with pytest.raises(RevisionError):
        repo.ensure_workspace(owner, project, heat)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT * FROM revision_workspaces ORDER BY id').fetchall() == before


def test_workspace_identity_rejects_heat_from_another_project(repository):
    repo, path, main, heat = repository
    engine = create_engine('sqlite:///' + path.as_posix())
    with Session(engine) as s:
        s.add(Project(id='other', user_id='owner', prompt='fixture', title='Other'))
        s.commit()
    engine.dispose()
    with pytest.raises(RevisionError, match='revision_not_found'):
        repo.ensure_workspace('owner', 'other', 'heat')
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM revision_workspaces WHERE project_id='other'").fetchone()[0] == 0


@pytest.mark.parametrize('state', ['reserved', 'cancelled', 'expired', 'registered', 'unknown', 'closed'])
def test_recovery_remains_readable_without_dispatch_or_database_effects(repository, monkeypatch, state):
    repo, path, main, heat = repository
    repo.bootstrap('owner',main,BASE)
    pending = repo.reserve('owner',main,'run','attempt','grant-attempt',int(time.time())+120)
    receipt = None
    if state in ('registered','closed'):
        repo.bind('owner','attempt','broker-attempt')
        receipt = register(repo)
    if state == 'cancelled':
        repo.cancel('owner','attempt')
    if state == 'unknown':
        repo.observe_termination('owner','attempt',confirmed=False,outcome='failed')
    if state == 'closed':
        repo.observe_termination('owner','attempt',confirmed=True,outcome='succeeded')
        allocate(repo,main,attempt='successor')
    if state == 'expired':
        monkeypatch.setattr('app.revisions.time.time',lambda: pending.deadline)
    with sqlite3.connect(path) as db:
        before = list(db.iterdump())
    recovered = RevisionRepository(path).recovery('owner','attempt')
    assert recovered.attempt_id == 'attempt' and recovered.workspace_id == main
    assert recovered.grant_id == 'grant-attempt' and recovered.deadline == pending.deadline
    assert recovered.broker_attempt_id == ('broker-attempt' if receipt else None)
    assert recovered.receipt == receipt
    assert recovered.state == ('closed' if state == 'closed' else
        'cancel_requested' if state in ('cancelled','unknown') else 'active')
    assert recovered.termination_state == ('confirmed' if state == 'closed' else
        'unknown' if state == 'unknown' else 'pending')
    assert recovered.outcome == ('succeeded' if state == 'closed' else 'cancelled' if state == 'cancelled' else None)
    assert not hasattr(recovered,'issued_at') and not hasattr(recovered,'base_revision')
    if state != 'reserved':
        with pytest.raises(RevisionError,match='revision_conflict'):
            repo.execution('owner','attempt')
    with sqlite3.connect(path) as db:
        assert list(db.iterdump()) == before
    with pytest.raises(RevisionError,match='revision_not_found'):
        repo.recovery('stranger','attempt')
    with pytest.raises(RevisionError,match='revision_not_found'):
        repo.recovery('owner','missing')


def test_cancel_returns_committed_recovery_and_preserves_closed_successor(repository):
    repo, path, main, heat = repository
    repo.bootstrap('owner',main,BASE)
    allocate(repo,main)
    receipt = register(repo)
    cancelled = repo.cancel('owner','attempt')
    assert cancelled.state == 'cancel_requested' and cancelled.receipt == receipt
    assert RevisionRepository(path).recovery('owner','attempt') == cancelled
    assert repo.cancel('owner','attempt') == cancelled
    repo.observe_termination('owner','attempt',confirmed=True,outcome='cancelled')
    successor = allocate(repo,main,attempt='successor')
    closed = repo.recovery('owner','attempt')
    assert repo.cancel('owner','attempt') == closed
    assert closed.outcome == 'cancelled' and closed.termination_state == 'confirmed'
    assert repo.execution('owner','successor') == successor
    with pytest.raises(RevisionError,match='revision_not_found'):
        repo.cancel('stranger','attempt')


def test_recovery_checks_current_owner_but_does_not_require_running_run(repository):
    repo, path, main, heat = repository
    repo.bootstrap('owner',main,BASE)
    allocate(repo,main)
    expected = repo.recovery('owner','attempt')
    with sqlite3.connect(path) as db:
        db.execute("UPDATE runs SET status='failed' WHERE id='run'")
        db.execute("UPDATE projects SET active_run_id=NULL WHERE id='p'")
    assert repo.recovery('owner','attempt') == expected
    with pytest.raises(RevisionError,match='revision_conflict'):
        repo.execution('owner','attempt')
    engine = create_engine('sqlite:///' + path.as_posix())
    with Session(engine) as session:
        session.add(User(id='new-owner',email='new@example.invalid',name='New',password_hash='fixture'))
        session.commit()
    engine.dispose()
    with sqlite3.connect(path) as db:
        db.execute("UPDATE projects SET user_id='new-owner' WHERE id='p'")
    with pytest.raises(RevisionError,match='revision_not_found'):
        repo.recovery('owner','attempt')
    assert repo.recovery('new-owner','attempt') == expected


@pytest.mark.parametrize('mode', ['disconnect', 'cancel_task', 'concurrent_close', 'startup_disconnect', 'startup_timeout'])
def test_coordinator_cancel_persists_intent_before_actual_transport(repository, mode):
    from app.execution import ExecutionCoordinator, ExecutionError
    from app.sandbox.client import BrokerClient, BrokerClientError
    from app.sandbox.grants import GrantCodec, CompletionGrantCodec
    repo, path, main, heat = repository
    repo.bootstrap('owner',main,BASE)
    allocate(repo,main)
    arrived, release = threading.Event(), threading.Event()
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append((self.path,body,repo.recovery('owner','attempt')))
            arrived.set()
            release.wait(timeout=5)
            self.close_connection = True  # Actual lost response; no fake success.
    server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread = threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    async def scenario():
        async with BrokerClient(f'http://127.0.0.1:{server.server_port}',secrets.token_urlsafe(32),
                                GrantCodec(b'k'*32),timeout=3) as client:
            coordinator = ExecutionCoordinator(repo,client,completion_codec=CompletionGrantCodec(b'c'*32))
            with pytest.raises(RevisionError,match='revision_not_found'):
                await coordinator.cancel('stranger','attempt')
            assert not requests
            task = asyncio.create_task(coordinator.reconcile(timeout=0.3 if mode == 'startup_timeout' else 60) if mode.startswith('startup_')
                                       else coordinator.cancel('owner','attempt'))
            assert await asyncio.to_thread(arrived.wait,3)
            assert requests[0][0:2] == ('/v1/admin/revoke',{'grant_id':'grant-attempt'})
            assert requests[0][2].state == 'cancel_requested'
            if mode == 'concurrent_close':
                repo.observe_termination('owner','attempt',confirmed=True,outcome='cancelled')
            if mode == 'cancel_task':
                task.cancel()
            if mode == 'startup_timeout':
                with pytest.raises(ExecutionError, match='execution_recovery_timeout'):
                    await task
                recovered = repo.recovery('owner','attempt')
                assert recovered.state == 'cancel_requested' and recovered.termination_state == 'unknown'
                assert recovered.outcome == 'failed'
                assert repo.pending_executions()[0].attempt_id == 'attempt'
                release.set()
                return
            release.set()
            if mode == 'concurrent_close':
                result = await task
                assert result.state == 'closed' and result.outcome == 'cancelled'
                assert await coordinator.cancel('owner','attempt') == result
                assert len(requests) == 1
            else:
                with pytest.raises(asyncio.CancelledError if mode == 'cancel_task' else BrokerClientError):
                    await task
                recovered = repo.recovery('owner','attempt')
                assert recovered.state == 'cancel_requested' and recovered.termination_state == 'unknown'
                assert recovered.outcome == ('failed' if mode == 'startup_disconnect' else 'cancelled')
                with pytest.raises(RevisionError,match='revision_conflict'):
                    allocate(repo,main,attempt='successor')
    try:
        asyncio.run(scenario())
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_reservation_survives_restart_and_binds_once(repository, monkeypatch):
    repo, path, main, heat = repository
    root = repo.bootstrap('owner',main,BASE)
    deadline = int(time.time())+120
    pending = repo.reserve('owner',main,'run','attempt','grant-attempt',deadline)
    assert pending.broker_attempt_id is None and pending.base_revision_id == root
    assert pending.project_id == 'p' and pending.base_artifact_key == BASE.key and pending.base_revision == BASE.revision
    assert pending.issued_at < pending.deadline and pending.generation == 1
    reopened = RevisionRepository(path)
    monkeypatch.setattr('app.revisions.time.time',lambda: pending.issued_at+2)
    assert reopened.execution('owner','attempt') == pending
    assert reopened.reserve('owner',main,'run','attempt','grant-attempt',deadline) == pending
    with pytest.raises(RevisionError,match='revision_conflict'):
        register(repo)
    bound = reopened.bind('owner','attempt','broker-attempt')
    assert bound.issued_at == pending.issued_at and bound.generation == 1
    assert reopened.bind('owner','attempt','broker-attempt') == bound
    with pytest.raises(RevisionError,match='revision_conflict'):
        reopened.bind('owner','attempt','other')


@pytest.mark.parametrize('reason',['cancel','expiry','uncertain'])
def test_unbound_reservation_rejects_late_binding_and_replacement(repository, monkeypatch, reason):
    repo, path, main, heat = repository
    repo.bootstrap('owner',main,BASE)
    pending = repo.reserve('owner',main,'run','attempt','grant-attempt',int(time.time())+120)
    if reason == 'cancel':
        repo.cancel('owner','attempt')
    elif reason == 'expiry':
        monkeypatch.setattr('app.revisions.time.time',lambda: pending.deadline)
    else:
        repo.observe_termination('owner','attempt',confirmed=False,outcome='failed')
    with pytest.raises(RevisionError,match='revision_conflict'):
        repo.bind('owner','attempt','broker-attempt')
    with pytest.raises(RevisionError,match='revision_conflict'):
        repo.execution('owner','attempt')
    with pytest.raises(RevisionError,match='revision_conflict'):
        repo.reserve('owner',main,'run','next','grant-next',int(time.time())+120)
    repo.observe_termination('owner','attempt',confirmed=True,outcome='cancelled')
    assert repo.reserve('owner',main,'run','next','grant-next',int(time.time())+120).generation == 2


@pytest.mark.parametrize('race',['bind','cancel'])
def test_binding_competition_preserves_one_identity_and_cancellation(repository, race):
    repo, path, main, heat = repository
    repo.bootstrap('owner',main,BASE)
    repo.reserve('owner',main,'run','attempt','grant-attempt',int(time.time())+120)
    barrier = threading.Barrier(2)
    def bind(identity):
        barrier.wait(timeout=5)
        try:
            return repo.bind('owner','attempt',identity)
        except RevisionError as error:
            assert error.code == 'revision_conflict'
            return None
    def cancel():
        barrier.wait(timeout=5)
        repo.cancel('owner','attempt')
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(bind,'broker-first')
        second = pool.submit(bind,'broker-second') if race == 'bind' else pool.submit(cancel)
        values = [first.result(timeout=10),second.result(timeout=10)]
    with sqlite3.connect(path) as db:
        identity,state,generation = db.execute('SELECT broker_attempt_id,state,generation FROM revision_attempts').fetchone()
        assert generation == 1
    if race == 'bind':
        successes = [value for value in values if value is not None]
        assert len(successes) == 1 and identity == successes[0].broker_attempt_id and state == 'active'
    else:
        assert state == 'cancel_requested' and identity in (None,'broker-first')
        with pytest.raises(RevisionError,match='revision_conflict'):
            register(repo)
        with pytest.raises(RevisionError,match='revision_conflict'):
            repo.bind('owner','attempt','broker-first')


def register(repo, attempt='attempt', artifact=OUTPUT, owner='owner'):
    return repo.register(owner, attempt, 'broker-' + attempt, 'grant-' + attempt, artifact)


@pytest.mark.parametrize('grant_id',['_invalid','g'*65])
def test_reservation_rejects_identity_that_broker_cannot_revoke(repository, grant_id):
    repo, path, main, heat = repository
    repo.bootstrap('owner',main,BASE)
    with pytest.raises(RevisionError,match='invalid_revision_request'):
        repo.reserve('owner',main,'run','attempt',grant_id,int(time.time())+120)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT COUNT(*) FROM revision_attempts').fetchone() == (0,)


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
    repo.decide_termination('owner','attempt','failed')
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
        with pytest.raises(RevisionError, match='revision_conflict'):
            repo.observe_termination('owner', attempt_id, confirmed=True, outcome='succeeded')
        repo.observe_termination('owner', attempt_id, confirmed=True, outcome='cancelled')
    successor = allocate(repo, main, attempt='successor')
    repo.cancel('owner', 'attempt-0')
    with pytest.raises(RevisionError, match='revision_not_found'):
        repo.receipt('stranger','attempt-0','broker-attempt-0','grant-attempt-0')
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT active_attempt_id,generation FROM revision_workspaces WHERE id=?',(main,)).fetchone() == ('successor',successor.generation)


def test_completion_authority_survives_registration_but_not_cancel_or_successor(repository):
    repo,path,main,heat=repository
    repo.bootstrap('owner',main,BASE)
    bound=allocate(repo,main)
    assert repo.completion('owner','attempt')==bound
    receipt=register(repo)
    assert RevisionRepository(path).completion('owner','attempt')==bound
    with pytest.raises(RevisionError,match='revision_conflict'): repo.execution('owner','attempt')
    with pytest.raises(RevisionError,match='revision_not_found'): repo.completion('stranger','attempt')
    repo.cancel('owner','attempt')
    with pytest.raises(RevisionError,match='revision_conflict'): repo.completion('owner','attempt')
    with pytest.raises(RevisionError,match='revision_conflict'):
        repo.observe_termination('owner','attempt',confirmed=True,outcome='succeeded')
    repo.observe_termination('owner','attempt',confirmed=True,outcome='cancelled')
    allocate(repo,main,attempt='successor')
    with pytest.raises(RevisionError,match='revision_conflict'): repo.completion('owner','attempt')
    assert repo.recovery('owner','attempt').receipt==receipt


def test_terminal_decision_is_durable_fences_dispatch_and_survives_unknown(repository):
    repo,path,main,heat=repository
    repo.bootstrap('owner',main,BASE)
    allocate(repo,main)
    with pytest.raises(RevisionError,match='revision_conflict'):
        repo.decide_termination('owner','attempt','succeeded')
    receipt=register(repo)
    intent=repo.decide_termination('owner','attempt','succeeded')
    assert intent.state!='closed' and intent.outcome=='succeeded' and intent.receipt==receipt
    assert RevisionRepository(path).recovery('owner','attempt')==intent
    assert repo.decide_termination('owner','attempt','failed')==intent
    with pytest.raises(RevisionError,match='revision_conflict'): repo.completion('owner','attempt')
    repo.observe_termination('owner','attempt',confirmed=False,outcome='succeeded')
    assert repo.recovery('owner','attempt').outcome=='succeeded'
    repo.observe_termination('owner','attempt',confirmed=True,outcome='succeeded')
    assert repo.recovery('owner','attempt').state=='closed'


def test_cancel_overrides_pending_success_without_erasing_receipt(repository):
    repo,path,main,heat=repository
    repo.bootstrap('owner',main,BASE)
    allocate(repo,main)
    receipt=register(repo)
    repo.decide_termination('owner','attempt','succeeded')
    intent=repo.cancel('owner','attempt')
    assert intent.outcome=='cancelled' and intent.receipt==receipt
    with pytest.raises(RevisionError,match='revision_conflict'):
        repo.observe_termination('owner','attempt',confirmed=True,outcome='succeeded')
    repo.observe_termination('owner','attempt',confirmed=True,outcome='cancelled')


@pytest.mark.parametrize('field,value',[('grant_id','other'),('project_id','other'),('run_id','other'),
    ('generation',2),('generation',True),('base_revision','f'*64),('issued_at',1),('deadline',1)])
def test_completion_capability_must_match_persisted_binding(repository,field,value):
    repo,path,main,heat=repository
    repo.bootstrap('owner',main,BASE)
    attempt=allocate(repo,main)
    binding=dict(grant_id=attempt.grant_id,project_id=attempt.project_id,run_id=attempt.run_id,
        generation=attempt.generation,base_revision=attempt.base_revision,
        issued_at=attempt.issued_at,deadline=attempt.deadline)
    assert repo.authorize_capability('owner','attempt',**binding)==repo.recovery('owner','attempt')
    with pytest.raises(RevisionError,match='revision_conflict'):
        repo.authorize_capability('owner','attempt',**{**binding,field:value})
    with pytest.raises(RevisionError,match='revision_not_found'):
        repo.authorize_capability('stranger','attempt',**binding)
    assert repo.execution('owner','attempt')==attempt


@pytest.mark.parametrize('mode',['missing','wrong','uncommitted'])
def test_runtime_broker_result_requires_matching_durable_success(repository, mode):
    from app.execution import ExecutionLease
    from app.services.runtime_client import RuntimeClient,GatewayConfig
    from app.errors import RuntimeUnavailable
    repo,path,main,heat=repository
    repo.bootstrap('owner',main,BASE)
    repo.reserve('owner',main,'run','attempt','grant-attempt',int(time.time())+120)
    repo.bind('owner','attempt','a'*32)
    deadline=repo.execution('owner','attempt').deadline
    lease=ExecutionLease('run',main,'a'*32,deadline,'attempt','grant-attempt','sandbox.token.value','completion.token.value')
    requests=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(request)
            self.send_response(200);self.send_header('Content-Type','application/x-ndjson');self.end_headers()
            receipt={'attempt_id':'attempt','workspace_id':main,'revision_id':'c'*32,
                     'artifact_key':'c'*64,'snapshot_revision':'d'*64}
            if mode != 'uncommitted':
                from dataclasses import asdict
                receipt=asdict(repo.register('owner','attempt','a'*32,'grant-attempt',OUTPUT))
                repo.observe_termination('owner','attempt',confirmed=True,outcome='succeeded')
            if mode=='wrong': receipt['workspace_id']='other'
            result={'kind':'result','resultText':'untrusted'}
            if mode!='missing': result['revisionReceipt']=receipt
            self.wfile.write((json.dumps(result)+'\n').encode())
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    async def scenario():
        client=RuntimeClient();client._base_url=f'http://127.0.0.1:{server.server_port}'
        with pytest.raises(RuntimeUnavailable):
            async for line in client.run(run_id='run',role='alex',prompt='test',workspace_path=Path('.'),
                session_path=Path('session'),agent_dir=Path('.'),gateway=GatewayConfig('https://invalid','test','model'),
                execution_lease=lease,execution_repository=repo,execution_owner='owner'):
                assert line.kind!='result'
    try: asyncio.run(scenario())
    finally:
        server.shutdown();server.server_close();thread.join(timeout=3)
    assert requests[0]['lease']=={'runId':'run','workspaceId':main,'attemptId':'a'*32,
        'executionId':'attempt','grantId':'grant-attempt','deadline':deadline,
        'grant':'sandbox.token.value','completionGrant':'completion.token.value'}


@pytest.mark.parametrize('damage',['future','definition','journal'])
def test_schema_drift_is_rejected_on_open_and_each_transaction(repository,damage):
    repo,path,main,_=repository
    with sqlite3.connect(path) as db:
        if damage=='future':db.execute('PRAGMA user_version=99')
        elif damage=='definition':db.execute('CREATE TABLE unexpected_runtime_table(id TEXT)')
        else:db.execute("UPDATE atom_schema_migrations SET migration_hash=? WHERE version=1",('f'*64,))
    with pytest.raises(RevisionError,match='revision_schema_required'):RevisionRepository(path)
    with pytest.raises(RevisionError,match='revision_unavailable'):repo.current_revision('owner',main)


@pytest.mark.parametrize('version',[2,3])
def test_intermediate_offline_schema_is_not_a_runtime_target(tmp_path,version):
    path=tmp_path/'intermediate.db'
    engine=create_engine('sqlite:///'+path.as_posix())
    Base.metadata.create_all(engine);engine.dispose()
    migrate(path,tmp_path/'before.db',target_version=version)
    with pytest.raises(RevisionError,match='revision_schema_required'):RevisionRepository(path)
