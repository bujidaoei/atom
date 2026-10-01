import sqlite3
import json
import subprocess
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.migrations import migrate, verify, verify_backup
from app.audit_governance import AuditGovernanceRepository, AuditGovernanceError
from test_revision_migrations import legacy


@pytest.fixture(params=[7,9])
def registry(legacy, monkeypatch, request):
    path, backup = legacy
    migrate(path, backup, target_version=request.param)
    monkeypatch.setattr('app.audit_governance.time.time', lambda: 100)
    return path, AuditGovernanceRepository(path)


def command(repo, action='register', generation=0, command_id='create', **extra):
    return repo.execute(command_id=command_id, operator_id='operator', destination_id='sink',
        scope_kind='account', scope_id='user', action=action, expected_generation=generation, **extra)


def test_lifecycle_restart_replay_and_stale_worker(registry):
    path, repo = registry
    first = command(repo)
    assert first.generation == 1 and first.state == 'active'
    command(repo, 'block', 1, 'block', reason='receiver_configuration')
    repo = AuditGovernanceRepository(path)
    assert repo.page()[0]['state'] == 'blocked'
    command(repo, 'resume', 2, 'resume')
    with pytest.raises(AuditGovernanceError, match='generation_conflict'):
        command(repo, 'block', 1, 'stale', reason='receiver_configuration')
    assert command(repo) == first  # Replay precedes current generation check.
    with pytest.raises(AuditGovernanceError, match='command_conflict'):
        command(repo, 'suspend', 3, 'create')
    command(repo, 'suspend', 3, 'pause')
    retired = command(repo, 'retire', 4, 'retire')
    assert retired.state == 'retired' and retired.required_through_sequence == 0
    with pytest.raises(AuditGovernanceError, match='transition_denied'):
        command(repo, 'resume', 5, 'revive')
    assert len(repo.page()) == 1
    assert repo.page(after='sink') == ()


def test_competing_commands_have_one_winner_and_receipt(registry):
    path, repo = registry
    command(repo)
    def change(index):
        try:
            return command(AuditGovernanceRepository(path), 'suspend', 1, 'pause'+str(index))
        except AuditGovernanceError as error:
            return str(error)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(change, range(2)))
    assert sum(isinstance(item, str) for item in results) == 1
    assert 'audit_generation_conflict' in results
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM security_audit_destination_commands').fetchone() == (2,)


def test_retirement_requires_even_never_enrolled_events(registry):
    path, repo = registry
    command(repo)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO security_audit_events(event_id,schema_version,event_kind,occurred_at,actor_kind,actor_id,scope_kind,scope_id,affected_count) VALUES (?,1,'console.account_sessions.revoked',90,'user','user','account','user',1)", ('a'*32,))
    with pytest.raises(AuditGovernanceError, match='outstanding_obligations'):
        command(repo, 'retire', 1, 'retire')
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO security_audit_delivery(event_id,destination_id,state,next_attempt_at) VALUES (?,'sink','pending',90)", ('a'*32,))
        db.execute("UPDATE security_audit_delivery SET state='leased',attempt=1,lease_owner=?,lease_expires_at=120", ('c'*32,))
    with pytest.raises(AuditGovernanceError, match='outstanding_obligations'):
        command(repo, 'retire', 1, 'retire')
    with sqlite3.connect(path) as db:
        db.execute("UPDATE security_audit_delivery SET state='delivered',lease_owner=NULL,lease_expires_at=NULL,delivered_at=99")
    assert command(repo, 'retire', 1, 'retire').required_through_sequence == 1


def test_receipt_failure_rolls_back_registry_and_replay_is_immutable(registry, monkeypatch):
    from contextlib import contextmanager
    path, repo = registry
    original = repo._transaction
    @contextmanager
    def failing(**kwargs):
        with original(**kwargs) as db:
            db.set_authorizer(lambda action, table, *_: sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_INSERT and table == 'security_audit_destination_commands' else sqlite3.SQLITE_OK)
            yield db
    with monkeypatch.context() as patch:
        patch.setattr(repo, '_transaction', failing)
        with pytest.raises(AuditGovernanceError, match='unavailable'):
            command(repo)
    assert repo.page() == ()
    command(repo)
    with sqlite3.connect(path) as db:
        for sql in ('DELETE FROM security_audit_destination_commands',
                    'UPDATE security_audit_destination_commands SET occurred_at=101',
                    'INSERT OR REPLACE INTO security_audit_destination_commands SELECT * FROM security_audit_destination_commands'):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(sql)


@pytest.mark.parametrize('source', range(7))
def test_seven_migration_backup_restore(legacy, tmp_path, source):
    path, initial = legacy
    if source:
        migrate(path, initial, target_version=source)
    backup = tmp_path/'before-seven.db'
    result = migrate(path, backup, target_version=7)
    assert result.applied and verify(path) == 7
    assert verify_backup(backup, expected_version=source) == result.backup_sha256
    restored = tmp_path/'restored.db'
    with sqlite3.connect(backup) as origin, sqlite3.connect(restored) as target:
        origin.backup(target)
    assert verify(restored) == source
    assert not migrate(path, backup, target_version=7).applied


@pytest.mark.parametrize('phase', ['before', 'after'])
@pytest.mark.parametrize('action', ['register', 'suspend', 'resume', 'block', 'retire'])
def test_actual_command_process_loss_preserves_atomic_receipt(registry, action, phase):
    path, repo = registry
    generation = 0
    if action != 'register':
        command(repo)
        generation = 1
    if action == 'resume':
        command(repo, 'suspend', 1, 'pause')
        generation = 2
    before = repo.page()
    code = '''
import json,os,sqlite3,sys
from pathlib import Path
from app.audit_governance import AuditGovernanceRepository
p=json.loads(sys.stdin.read())
original=sqlite3.connect
class Connection(sqlite3.Connection):
    def execute(self,sql,*args,**kwargs):
        if sql=='COMMIT' and p['phase']=='before':os._exit(71)
        result=super().execute(sql,*args,**kwargs)
        if sql=='COMMIT' and p['phase']=='after':os._exit(72)
        return result
sqlite3.connect=lambda *args,**kwargs: original(*args,**dict(kwargs,factory=Connection))
repo=AuditGovernanceRepository(Path(p['path']))
repo.execute(command_id='crash',operator_id='operator',destination_id='sink',scope_kind='account',scope_id='user',action=p['action'],expected_generation=p['generation'],reason='receiver_configuration' if p['action']=='block' else None)
'''
    result = subprocess.run([sys.executable, '-c', code], input=json.dumps(dict(path=str(path), phase=phase, action=action, generation=generation)).encode(),
        cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=15)
    assert result.returncode == (71 if phase == 'before' else 72), result.stderr.decode()
    assert not result.stdout and not result.stderr
    with sqlite3.connect(path) as db:
        count = db.execute("SELECT count(*) FROM security_audit_destination_commands WHERE command_id='crash'").fetchone()[0]
        assert count == int(phase == 'after')
        assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)
    if phase == 'before':
        assert repo.page() == before
    result = command(repo, action, generation, 'crash', reason='receiver_configuration' if action == 'block' else None)
    assert result.generation == generation+1
    assert command(repo, action, generation, 'crash', reason='receiver_configuration' if action == 'block' else None) == result


def test_actual_operator_cli_replay_list_and_conflict(registry):
    path, _ = registry
    prefix = [sys.executable, '-m', 'app.audit_admin', '--database', str(path)]
    create = ['apply', '--command-id', 'cli', '--operator-id', 'operator', '--destination-id', 'sink',
        '--scope-kind', 'account', '--scope-id', 'user', '--action', 'register', '--expected-generation', '0']
    def run(args, expected=0):
        result = subprocess.run(prefix+args, cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=15)
        assert result.returncode == expected, result.stderr.decode()
        assert not result.stderr
        return json.loads(result.stdout)
    first = run(create)
    assert run(create) == first
    listing = run(['list', '--limit', '1'])
    assert listing['destinations'][0]['state'] == 'active' and listing['next_after'] == 'sink'
    assert run(['list', '--after', 'sink'])['destinations'] == []
    changed = create.copy()
    changed[changed.index('operator')] = 'another'
    assert run(changed, 1)['error'] == 'audit_command_conflict'


@pytest.mark.parametrize('options', [dict(expected_generation=True),dict(expected_generation=-1),
    dict(expected_generation=2**63-1),dict(action='erase'),dict(operator_id='../operator'),dict(command_id=''),
    dict(destination_id='x'*65),dict(scope_kind='global'),dict(reason='secret'),dict(action='block')])
def test_invalid_commands_have_no_effect(registry, options):
    _, repo = registry
    args=dict(command_id='create', operator_id='operator', destination_id='sink', scope_kind='account',
        scope_id='user', action='register', expected_generation=0)
    with pytest.raises(AuditGovernanceError, match='invalid_audit_governance_request'):
        repo.execute(**(args|options))
    assert repo.page() == ()


def test_registry_reads_are_unchanged_and_schema_drift_denies(registry):
    path, repo = registry
    command(repo)
    with sqlite3.connect(path) as db:
        before = list(db.iterdump())
        db.execute('BEGIN IMMEDIATE')
        assert repo.page()[0]['destination_id'] == 'sink'
        assert list(db.iterdump()) == before
        db.rollback()
        db.execute('CREATE TABLE unexpected(id INTEGER)')
    with pytest.raises(AuditGovernanceError, match='unavailable'):
        repo.page()


def test_historical_unconfigured_destination_survives_seven(legacy, tmp_path):
    from test_audit_governance_migration import history
    path, backup = legacy
    migrate(path, backup, target_version=5)
    history(path)
    migrate(path, tmp_path/'five.db', target_version=6)
    with sqlite3.connect(path) as db:
        before = db.execute('SELECT * FROM security_audit_destinations').fetchall()
    migrate(path, tmp_path/'six.db', target_version=7)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT * FROM security_audit_destinations').fetchall() == before
        assert db.execute('SELECT count(*) FROM security_audit_destination_commands').fetchone() == (0,)
    repo = AuditGovernanceRepository(path)
    assert repo.page()[0]['state'] == 'unconfigured'
    resumed = repo.execute(command_id='resume-old', operator_id='operator', destination_id='removed-sink',
        scope_kind='account', scope_id='user', action='resume', expected_generation=1)
    assert resumed.generation == 2 and resumed.state == 'active'


@pytest.mark.parametrize('phase', ['before', 'after'])
def test_migration_process_loss_reopens_and_replays(legacy, tmp_path, phase):
    path, backup = legacy
    migrate(path, backup, target_version=6)
    code = '''
import os,sqlite3,sys
from pathlib import Path
from app.migrations import migrate
original=sqlite3.connect
class Connection(sqlite3.Connection):
    def execute(self,sql,*args,**kwargs):
        if sql=='COMMIT' and sys.argv[3]=='before':os._exit(71)
        result=super().execute(sql,*args,**kwargs)
        if sql=='COMMIT' and sys.argv[3]=='after':os._exit(72)
        return result
sqlite3.connect=lambda *args,**kwargs: original(*args,**dict(kwargs,factory=Connection))
migrate(Path(sys.argv[1]),Path(sys.argv[2]),target_version=7)
'''
    saved = tmp_path/'before-seven.db'
    result = subprocess.run([sys.executable, '-c', code, str(path), str(saved), phase],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=15)
    assert result.returncode == (71 if phase == 'before' else 72), result.stderr.decode()
    assert verify(path) == (6 if phase == 'before' else 7)
    assert verify_backup(saved, expected_version=6)
    retried = migrate(path, tmp_path/'retry-seven.db', target_version=7)
    assert retried.applied == (phase == 'before')
    assert verify(path) == 7


def test_late_seven_ddl_failure_preserves_six(legacy, tmp_path, monkeypatch):
    from app.migrations import audit_commands_v7, MigrationError
    path, backup = legacy
    migrate(path, backup, target_version=6)
    with sqlite3.connect(path) as db:
        before = list(db.iterdump())
    original = audit_commands_v7.apply
    def fail(db):
        original(db)
        raise sqlite3.OperationalError('injected_late_failure')
    monkeypatch.setattr(audit_commands_v7, 'apply', fail)
    with pytest.raises(MigrationError):
        migrate(path, tmp_path/'late.db', target_version=7)
    assert verify(path) == 6 and verify_backup(tmp_path/'late.db', expected_version=6)
    with sqlite3.connect(path) as db:
        assert list(db.iterdump()) == before
