import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from app.audit_delivery import AuditDeliveryRepository
from app.audit_governance import AuditGovernanceRepository
from app.audit_retention import RetentionRepository, RetentionError
from app.migrations import migrate
from test_audit_repository import reader, audited_release, release, ledger, legacy
from test_audit_retention import args


@pytest.fixture
def planned(reader, tmp_path, monkeypatch):
    path, _, access, _, _ = reader
    for _ in range(2):
        access.create_console_session(user_id='user', lifetime_seconds=60)
    migrate(path, tmp_path/'before-seven.db', target_version=7)
    AuditGovernanceRepository(path).execute(command_id='register',operator_id='operator',destination_id='sink',
        scope_kind='account',scope_id='user',action='register',expected_generation=0)
    delivery = AuditDeliveryRepository(path,destination_id='sink',scope_kind='account',scope_id='user')
    delivery.enroll()
    lease = delivery.claim()
    delivery.acknowledge(event_ids=[e['event_id'] for e in lease.events],lease_owner=lease.owner)
    migrate(path, tmp_path/'before-eight.db', target_version=8)
    monkeypatch.setattr('app.audit_retention.time.time', lambda: 200)
    repo = RetentionRepository(path)
    repo.execute(**args(state='active',min_age_seconds=50))
    return path, repo


def plan(repo, **extra):
    return repo.plan(policy_id='policy',expected_generation=1,**extra)


def test_actual_events_snapshot_candidates_digest_and_no_writes(planned):
    path, repo = planned
    with sqlite3.connect(path) as db:
        before = list(db.iterdump())
        db.execute('BEGIN IMMEDIATE')
        result = plan(repo)
        assert list(db.iterdump()) == before
        db.rollback()
    assert result['candidate_count'] == 3 and result['blocked_count'] == 0
    assert not result['deletion_authorized'] and result['archive_store_validation'] == 'not_performed'
    assert result['next_after'] is None
    digest = result.pop('plan_sha256')
    assert digest == hashlib.sha256(json.dumps(result,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()
    assert {item['event']['scope_id'] for item in result['items']} == {'user'}
    assert all(item['event']['event_kind'] == 'console.session.created' for item in result['items'])


def test_limits_continue_without_skipping_and_freeze_upper(planned):
    path, repo = planned
    first = plan(repo,limit=1)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO security_audit_events(event_id,schema_version,event_kind,occurred_at,actor_kind,actor_id,scope_kind,scope_id,affected_count) VALUES (?,1,'console.session.created',100,'user','user','account','user',1)", ('f'*32,))
    page = plan(repo,after=first['next_after'],upper=first['upper_sequence'],expected_context=first['context_sha256'])
    assert page['candidate_count'] == 2 and page['next_after'] is None
    assert all(item['event']['sequence'] <= first['upper_sequence'] for item in page['items'])
    assert len(plan(repo)['items']) == 4
    bounded = plan(repo,max_bytes=1800)
    assert bounded['next_after'] is not None
    assert len(json.dumps(bounded,sort_keys=True,separators=(',',':')).encode()) <= 1800


def test_hold_and_policy_revision_invalidate_old_context(planned):
    _, repo = planned
    first = plan(repo)
    repo.execute(**args('place_hold',1,'hold',hold_id='hold',hold_kind='legal'))
    with pytest.raises(RetentionError,match='generation_conflict'):
        plan(repo)
    with pytest.raises(RetentionError,match='context_conflict'):
        repo.plan(policy_id='policy',expected_generation=2,expected_context=first['context_sha256'])
    held = repo.plan(policy_id='policy',expected_generation=2)
    assert held['candidate_count'] == 0
    assert all('active_hold' in row['blocked_reasons'] for row in held['items'])
    repo.execute(**args('update_policy',2,'pause',state='paused',min_age_seconds=150))
    blocked = repo.plan(policy_id='policy',expected_generation=3)
    assert all(row['blocked_reasons'] == ['policy_paused','active_hold','minimum_age'] for row in blocked['items'])


def test_new_removed_or_blocked_receiver_cannot_be_omitted(planned):
    path, repo = planned
    first = plan(repo)
    # Direct constrained registry mutation probes context fencing; governance8 API is a separate gate.
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO security_audit_destinations(destination_id,scope_kind,scope_id,generation,state,created_at,updated_at) VALUES ('removed','account','user',1,'unconfigured',100,100)")
    with pytest.raises(RetentionError,match='context_conflict'):
        plan(repo,expected_context=first['context_sha256'])
    blocked = plan(repo)
    assert blocked['candidate_count'] == 0
    assert all(row['blocked_reasons'] == ['unconfirmed_delivery'] and row['unconfirmed_destinations'] == 1 for row in blocked['items'])
    with sqlite3.connect(path) as db:
        db.execute("UPDATE security_audit_destinations SET generation=2,state='blocked',blocked_reason='receiver_configuration',blocked_at=100 WHERE destination_id='removed'")
    with pytest.raises(RetentionError,match='context_conflict'):
        plan(repo,expected_context=blocked['context_sha256'])


@pytest.mark.parametrize('options', [dict(after=1),dict(upper=2**63),dict(after=-1),dict(limit=101),
    dict(limit=True),dict(max_bytes=262145),dict(expected_context='bad'),dict(upper=True)])
def test_invalid_requests_fail_closed(planned, options):
    with pytest.raises(RetentionError,match='invalid_retention_plan'):
        plan(planned[1],**options)


def test_metadata_and_single_event_capacity_fail_closed(planned):
    _, repo = planned
    for maximum in (1,1000):
        with pytest.raises(RetentionError,match='payload_capacity'):
            plan(repo,max_bytes=maximum)


def test_actual_cli_reports_candidates_not_delete_authority(planned):
    path, _ = planned
    command = [sys.executable,'-m','app.retention_admin','--database',str(path),'plan','--policy-id','policy','--expected-generation','1','--limit','1']
    result = subprocess.run(command,cwd=Path(__file__).resolve().parents[1],capture_output=True,timeout=15)
    assert result.returncode == 0 and not result.stderr
    decoded = json.loads(result.stdout)
    assert decoded['ok'] and decoded['plan']['candidate_count'] == 1
    assert not decoded['plan']['deletion_authorized']


@pytest.mark.parametrize('kind', ['destinations','holds'])
def test_excess_context_never_yields_partial_eligibility(planned, kind):
    path, repo = planned
    generation = 1
    if kind == 'destinations':
        with sqlite3.connect(path) as db:
            db.executemany("INSERT INTO security_audit_destinations(destination_id,scope_kind,scope_id,generation,state,created_at,updated_at) VALUES (?,'account','user',1,'unconfigured',100,100)",
                [(f'sink-{index}',) for index in range(100)])
    else:
        for index in range(101):
            repo.execute(**args('place_hold',generation,f'hold-{index}',hold_id=f'hold-{index}',hold_kind='operational'))
            generation += 1
    with pytest.raises(RetentionError,match='context_capacity'):
        repo.plan(policy_id='policy',expected_generation=generation)


def test_new_events_after_all_receivers_retire_have_no_required_destination(planned):
    path, repo = planned
    upper = plan(repo)['upper_sequence']
    with sqlite3.connect(path) as db:
        db.execute("UPDATE security_audit_destinations SET generation=2,state='retired',required_through_sequence=? WHERE destination_id='sink'", (upper,))
        db.execute("INSERT INTO security_audit_events(event_id,schema_version,event_kind,occurred_at,actor_kind,actor_id,scope_kind,scope_id,affected_count) VALUES (?,1,'console.session.created',100,'user','user','account','user',1)", ('f'*32,))
    result = plan(repo)
    assert result['candidate_count'] == 3 and result['blocked_count'] == 1
    assert result['items'][-1]['blocked_reasons'] == ['no_required_destination']


def test_real_concurrent_hold_keeps_plan_snapshot_consistent(planned, monkeypatch):
    path, repo = planned
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA journal_mode=WAL').fetchone() == ('wal',)
    original = sqlite3.connect
    inserted = []
    def connect(*connect_args, **kwargs):
        db = original(*connect_args, **kwargs)
        if '?mode=ro' in str(connect_args[0]):
            def trace(sql):
                if sql.startswith('SELECT hold_id,kind,policy_generation') and not inserted:
                    inserted.append(True)
                    repo.execute(**args('place_hold',1,'concurrent',hold_id='concurrent',hold_kind='legal'))
            db.set_trace_callback(trace)
        return db
    with monkeypatch.context() as patch:
        patch.setattr('app.audit_retention.sqlite3.connect', connect)
        previous = plan(repo)
    assert inserted and previous['candidate_count'] == 3
    assert previous['context']['policy']['generation'] == 1 and previous['context']['active_holds'] == []
    with pytest.raises(RetentionError,match='generation_conflict'):
        plan(repo)
    held = repo.plan(policy_id='policy',expected_generation=2)
    assert held['candidate_count'] == 0 and held['blocked_count'] == 3
