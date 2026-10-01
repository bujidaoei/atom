from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from app.audit_retention import RetentionRepository, RetentionError
from app.migrations import migrate
from test_revision_migrations import legacy


@pytest.fixture(params=[8,9,10])
def retention(legacy, monkeypatch, request):
    path, backup = legacy
    migrate(path, backup, target_version=request.param)
    monkeypatch.setattr('app.audit_retention.time.time', lambda: 100)
    return path, RetentionRepository(path)


def args(action='create_policy', generation=0, command='create', **extra):
    result = dict(command_id=command, policy_id='policy', operator_id='operator', action=action, expected_generation=generation)
    if action == 'create_policy':
        result.update(scope_kind='account', scope_id='user', event_kind='console.session.created')
    if action in ('create_policy','update_policy'):
        result.update(state='paused',min_age_seconds=86400,archive_store_id='archive')
    return result | extra


def test_independent_holds_replay_and_stale_updates(retention):
    path, repo = retention
    created = repo.execute(**args())
    repo.execute(**args('place_hold',1,'legal',hold_id='legal',hold_kind='legal'))
    repo.execute(**args('place_hold',2,'incident',hold_id='incident',hold_kind='operational'))
    repo.execute(**args('release_hold',3,'release',hold_id='legal'))
    repo = RetentionRepository(path)
    assert repo.policies()[0]['active_holds'] == 1
    assert [(row['hold_id'],row['state']) for row in repo.holds(policy_id='policy')] == [('incident','active'),('legal','released')]
    assert repo.execute(**args()) == created
    with pytest.raises(RetentionError, match='command_conflict'):
        repo.execute(**args(min_age_seconds=1))
    with pytest.raises(RetentionError, match='generation_conflict'):
        repo.execute(**args('update_policy',1,'stale'))
    with pytest.raises(RetentionError, match='hold_conflict'):
        repo.execute(**args('place_hold',4,'reuse',hold_id='legal',hold_kind='legal'))
    assert repo.execute(**args('update_policy',4,'enable',state='active')).generation == 5
    assert repo.policies()[0]['active_holds'] == 1  # Enabling policy never releases a hold.


def test_concurrent_hold_and_policy_change_have_one_winner(retention):
    path, repo = retention
    repo.execute(**args())
    changes = [args('update_policy',1,'update'), args('place_hold',1,'hold',hold_id='hold',hold_kind='operational')]
    def run(payload):
        try:
            return RetentionRepository(path).execute(**payload)
        except RetentionError as error:
            return str(error)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, changes))
    assert results.count('retention_generation_conflict') == 1
    assert repo.policies()[0]['generation'] == 2
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM security_audit_retention_commands').fetchone() == (2,)


def test_receipt_insert_failure_rolls_back_policy_and_hold(retention, monkeypatch):
    path, repo = retention
    repo.execute(**args())
    original = repo._transaction
    @contextmanager
    def failing(**kwargs):
        with original(**kwargs) as db:
            db.set_authorizer(lambda action, table, *_: sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_INSERT and table == 'security_audit_retention_commands' else sqlite3.SQLITE_OK)
            yield db
    with monkeypatch.context() as patch:
        patch.setattr(repo, '_transaction', failing)
        with pytest.raises(RetentionError, match='unavailable'):
            repo.execute(**args('place_hold',1,'hold',hold_id='hold',hold_kind='legal'))
    assert repo.policies()[0]['generation'] == 1 and repo.holds(policy_id='policy') == ()


@pytest.mark.parametrize('action', ['create_policy','update_policy','place_hold','release_hold'])
@pytest.mark.parametrize('phase', ['before','after'])
def test_actual_process_exit_retains_atomic_authority(retention, action, phase):
    path, repo = retention
    generation = 0
    if action != 'create_policy':
        repo.execute(**args())
        generation = 1
    if action == 'release_hold':
        repo.execute(**args('place_hold',1,'hold',hold_id='hold',hold_kind='legal'))
        generation = 2
    options = dict(hold_id='hold',hold_kind='legal') if action == 'place_hold' else dict(hold_id='hold') if action == 'release_hold' else {}
    payload = args(action,generation,'crash',**options)
    before = (repo.policies(), repo.holds(policy_id='policy') if generation else ())
    code = '''
import json,os,sqlite3,sys
from pathlib import Path
from app.audit_retention import RetentionRepository
p=json.loads(sys.stdin.read())
original=sqlite3.connect
class Connection(sqlite3.Connection):
    def execute(self,sql,*args,**kwargs):
        if sql=='COMMIT' and p['phase']=='before':os._exit(71)
        result=super().execute(sql,*args,**kwargs)
        if sql=='COMMIT' and p['phase']=='after':os._exit(72)
        return result
sqlite3.connect=lambda *args,**kwargs:original(*args,**dict(kwargs,factory=Connection))
RetentionRepository(Path(p['path'])).execute(**p['command'])
'''
    result = subprocess.run([sys.executable,'-c',code],input=json.dumps(dict(path=str(path),phase=phase,command=payload)).encode(),
        cwd=Path(__file__).resolve().parents[1],capture_output=True,timeout=15)
    assert result.returncode == (71 if phase == 'before' else 72), result.stderr.decode()
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM security_audit_retention_commands WHERE command_id='crash'").fetchone() == (int(phase == 'after'),)
        assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)
    if phase == 'before':
        assert repo.policies() == before[0]
        if generation:
            assert repo.holds(policy_id='policy') == before[1]
    receipt = repo.execute(**payload)
    assert receipt.generation == generation+1 and repo.execute(**payload) == receipt


@pytest.mark.parametrize('options', [dict(expected_generation=True),dict(expected_generation=-1),dict(min_age_seconds=0),
    dict(min_age_seconds=True),dict(min_age_seconds=2**63),dict(scope_kind='project'),dict(archive_store_id='https://store'),
    dict(operator_id='../operator'),dict(state='enabled'),dict(hold_id='extra')])
def test_invalid_input_does_not_create_policy(retention, options):
    _, repo = retention
    with pytest.raises(RetentionError, match='invalid_retention_request'):
        repo.execute(**args(**options))
    assert repo.policies() == ()


def test_actual_cli_and_readonly_pages(retention):
    path, repo = retention
    prefix = [sys.executable,'-m','app.retention_admin','--database',str(path)]
    command = ['apply']
    for key,value in args().items():
        command.extend(['--'+key.replace('_','-'),str(value)])
    def run(arguments, expected=0):
        result = subprocess.run(prefix+arguments,cwd=Path(__file__).resolve().parents[1],capture_output=True,timeout=15)
        assert result.returncode == expected and not result.stderr
        return json.loads(result.stdout)
    first = run(command)
    assert run(command) == first
    assert run(['policies','--limit','1'])['next_after'] == 'policy'
    assert run(['policies','--after','policy'])['policies'] == []
    with sqlite3.connect(path) as db:
        before = list(db.iterdump())
        db.execute('BEGIN IMMEDIATE')
        assert repo.policies()[0]['active_holds'] == 0
        assert repo.holds(policy_id='policy') == ()
        assert list(db.iterdump()) == before
        db.rollback()
        db.execute('CREATE TABLE unexpected(id INTEGER)')
    assert run(['policies'],1)['error'] == 'retention_schema_required'


def test_scope_uniqueness_cross_policy_hold_and_backward_clock(retention, monkeypatch):
    _, repo = retention
    repo.execute(**args())
    with pytest.raises(RetentionError, match='policy_conflict'):
        repo.execute(**args(command='duplicate',policy_id='duplicate'))
    with pytest.raises(RetentionError, match='scope_not_found'):
        repo.execute(**args(command='missing',policy_id='missing',scope_id='missing'))
    repo.execute(**args(command='project',policy_id='project-policy',scope_kind='project',scope_id='project',event_kind='release.published'))
    monkeypatch.setattr('app.audit_retention.time.time', lambda: 200)
    repo.execute(**args('place_hold',1,'hold',hold_id='hold',hold_kind='legal'))
    with pytest.raises(RetentionError, match='hold_conflict'):
        repo.execute(**args('release_hold',1,'foreign',policy_id='project-policy',hold_id='hold'))
    monkeypatch.setattr('app.audit_retention.time.time', lambda: 90)
    receipt = repo.execute(**args('update_policy',2,'update',state='active'))
    assert receipt.occurred_at == 200
    assert repo.holds(policy_id='policy')[0]['state'] == 'active'
    assert repo.policies()[0]['generation'] == 3


@pytest.mark.parametrize('options', [dict(limit=0),dict(limit=101),dict(limit=True),dict(after='../policy')])
def test_read_bounds_fail_closed(retention, options):
    _, repo = retention
    with pytest.raises(RetentionError, match='invalid_retention_request'):
        repo.policies(**options)
