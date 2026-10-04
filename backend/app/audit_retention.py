"""Trusted local policy/hold authority; does not archive or delete audit data."""
from contextlib import contextmanager
from dataclasses import dataclass, asdict
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time

from .migrations import MigrationError, _schema, verify
from .audit_repository import _FIELDS


class RetentionError(RuntimeError):
    pass


@dataclass(frozen=True)
class RetentionReceipt:
    command_id: str
    policy_id: str
    operator_id: str
    action: str
    request_sha256: str
    expected_generation: int
    generation: int
    state: str
    min_age_seconds: int
    archive_store_id: str
    hold_id: str | None
    hold_kind: str | None
    hold_state: str | None
    occurred_at: int


def _identifier(value, maximum=100):
    if not isinstance(value, str) or re.fullmatch(r'[A-Za-z0-9_.-]{1,'+str(maximum)+'}', value) is None:
        raise RetentionError('invalid_retention_request')


class RetentionRepository:
    _versions = (8, 9, 10, 13, 14, 15, 16, 17, 18, 19)

    def __init__(self, path):
        self.path = Path(path)
        try:
            if verify(self.path) not in self._versions:
                raise RetentionError('retention_schema_required')
        except MigrationError:
            raise RetentionError('retention_schema_required') from None

    @contextmanager
    def _transaction(self, *, read_only=False):
        db = None
        try:
            db = sqlite3.connect(self.path.as_uri()+('?mode=ro' if read_only else '?mode=rw'), uri=True,
                                 timeout=3, isolation_level=None)
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA synchronous=FULL')
            deadline = time.monotonic()+5
            db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            db.execute('BEGIN' if read_only else 'BEGIN IMMEDIATE')
            if _schema(db) not in self._versions:
                raise RetentionError('retention_schema_required')
            db.row_factory = sqlite3.Row
            yield db
            db.execute('COMMIT')
        except (sqlite3.Error, OSError, MigrationError):
            raise RetentionError('retention_unavailable') from None
        finally:
            if db is not None:
                if db.in_transaction:
                    db.rollback()
                db.close()

    def execute(self, *, command_id, policy_id, operator_id, action, expected_generation,
                scope_kind=None, scope_id=None, event_kind=None, state=None, min_age_seconds=None,
                archive_store_id=None, hold_id=None, hold_kind=None):
        for value in (command_id, policy_id, operator_id):
            _identifier(value)
        if (action not in ('create_policy','update_policy','place_hold','release_hold') or
                type(expected_generation) is not int or not 0 <= expected_generation < 2**63-1):
            raise RetentionError('invalid_retention_request')
        if action == 'create_policy':
            _identifier(scope_id)
            kinds = {'account': ('console.session.created','console.session.revoked','console.account_sessions.revoked'),
                     'project': ('content.handoff.issued','content.session.created','release.published','release.unpublished')}
            if not isinstance(scope_kind, str) or event_kind not in kinds.get(scope_kind, ()):
                raise RetentionError('invalid_retention_request')
        elif any(value is not None for value in (scope_kind, scope_id, event_kind)):
            raise RetentionError('invalid_retention_request')
        if action in ('create_policy','update_policy'):
            _identifier(archive_store_id, 64)
            if (state not in ('active','paused') or type(min_age_seconds) is not int or
                    not 1 <= min_age_seconds < 2**63 or hold_id is not None or hold_kind is not None):
                raise RetentionError('invalid_retention_request')
        else:
            _identifier(hold_id)
            if (any(value is not None for value in (state,min_age_seconds,archive_store_id)) or
                    (action == 'place_hold' and hold_kind not in ('legal','operational')) or
                    (action == 'release_hold' and hold_kind is not None)):
                raise RetentionError('invalid_retention_request')
        request = dict(command_id=command_id,policy_id=policy_id,operator_id=operator_id,action=action,
            expected_generation=expected_generation,scope_kind=scope_kind,scope_id=scope_id,event_kind=event_kind,
            state=state,min_age_seconds=min_age_seconds,archive_store_id=archive_store_id,hold_id=hold_id,hold_kind=hold_kind)
        digest = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        with self._transaction() as db:
            previous = db.execute('SELECT * FROM security_audit_retention_commands WHERE command_id=?', (command_id,)).fetchone()
            if previous:
                if previous['request_sha256'] != digest:
                    raise RetentionError('retention_command_conflict')
                return RetentionReceipt(**dict(previous))
            policy = db.execute('SELECT * FROM security_audit_retention_policies WHERE policy_id=?', (policy_id,)).fetchone()
            now = int(time.time())
            if not 0 <= now < 2**63:
                raise RetentionError('retention_clock_unavailable')
            generation = expected_generation+1
            hold_state = None
            if action == 'create_policy':
                if expected_generation != 0 or policy is not None:
                    raise RetentionError('retention_generation_conflict')
                table = 'users' if scope_kind == 'account' else 'projects'
                if db.execute('SELECT 1 FROM '+table+' WHERE id=?', (scope_id,)).fetchone() is None:
                    raise RetentionError('retention_scope_not_found')
                if db.execute('SELECT 1 FROM security_audit_retention_policies WHERE scope_kind=? AND scope_id=? AND event_kind=?',
                              (scope_kind, scope_id, event_kind)).fetchone():
                    raise RetentionError('retention_policy_conflict')
                db.execute('INSERT INTO security_audit_retention_policies VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (policy_id,scope_kind,scope_id,event_kind,generation,state,min_age_seconds,archive_store_id,now,now))
            else:
                if policy is None:
                    raise RetentionError('retention_policy_not_found')
                if policy['generation'] != expected_generation:
                    raise RetentionError('retention_generation_conflict')
                now = max(now, policy['updated_at'])
                if action in ('place_hold','release_hold'):
                    state, min_age_seconds, archive_store_id = policy['state'], policy['min_age_seconds'], policy['archive_store_id']
                    hold = db.execute('SELECT * FROM security_audit_retention_holds WHERE hold_id=?', (hold_id,)).fetchone()
                    if action == 'place_hold' and hold is not None:
                        raise RetentionError('retention_hold_conflict')
                    if action == 'release_hold':
                        if hold is None or hold['policy_id'] != policy_id or hold['state'] != 'active':
                            raise RetentionError('retention_hold_conflict')
                        hold_kind = hold['kind']
                    hold_state = 'active' if action == 'place_hold' else 'released'
                db.execute('UPDATE security_audit_retention_policies SET generation=?,state=?,min_age_seconds=?,archive_store_id=?,updated_at=? '
                    'WHERE policy_id=? AND generation=?', (generation,state,min_age_seconds,archive_store_id,now,policy_id,expected_generation))
                if action == 'place_hold':
                    db.execute('INSERT INTO security_audit_retention_holds VALUES (?,?,?,?,?,?,?)',
                        (hold_id,policy_id,hold_kind,hold_state,generation,now,now))
                elif action == 'release_hold':
                    db.execute('UPDATE security_audit_retention_holds SET state=?,policy_generation=?,updated_at=? WHERE hold_id=?',
                        (hold_state,generation,now,hold_id))
            receipt = RetentionReceipt(command_id,policy_id,operator_id,action,digest,expected_generation,generation,
                state,min_age_seconds,archive_store_id,hold_id,hold_kind,hold_state,now)
            values = asdict(receipt)
            db.execute('INSERT INTO security_audit_retention_commands ('+','.join(values)+') VALUES ('+','.join('?' for _ in values)+')', tuple(values.values()))
            return receipt

    @staticmethod
    def _page_bounds(after, limit):
        if after != '':
            _identifier(after)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise RetentionError('invalid_retention_request')

    def policies(self, *, after='', limit=50):
        self._page_bounds(after, limit)
        with self._transaction(read_only=True) as db:
            rows = db.execute('SELECT p.*,(SELECT count(*) FROM security_audit_retention_holds h WHERE h.policy_id=p.policy_id '
                "AND h.state='active') AS active_holds FROM security_audit_retention_policies p WHERE policy_id>? ORDER BY policy_id LIMIT ?",
                (after,limit)).fetchall()
            return tuple(dict(row) for row in rows)

    def holds(self, *, policy_id, after='', limit=50):
        _identifier(policy_id)
        self._page_bounds(after, limit)
        with self._transaction(read_only=True) as db:
            if db.execute('SELECT 1 FROM security_audit_retention_policies WHERE policy_id=?', (policy_id,)).fetchone() is None:
                raise RetentionError('retention_policy_not_found')
            rows = db.execute('SELECT * FROM security_audit_retention_holds WHERE policy_id=? AND hold_id>? ORDER BY hold_id LIMIT ?',
                              (policy_id,after,limit)).fetchall()
            return tuple(dict(row) for row in rows)

    def plan(self, *, policy_id, expected_generation, after=0, upper=None, expected_context=None,
             limit=100, max_bytes=262144):
        with self._transaction(read_only=True) as db:
            return self._plan_snapshot(db, policy_id=policy_id, expected_generation=expected_generation,
                after=after, upper=upper, expected_context=expected_context, limit=limit, max_bytes=max_bytes)

    def _plan_snapshot(self, db, *, policy_id, expected_generation, after=0, upper=None, expected_context=None,
             limit=100, max_bytes=262144):
        """Bounded snapshot candidates only; no archive validation or deletion grant."""
        _identifier(policy_id)
        if (type(expected_generation) is not int or not 1 <= expected_generation < 2**63 or
                type(after) is not int or not 0 <= after < 2**63 or
                (upper is not None and (type(upper) is not int or not after <= upper < 2**63)) or
                type(limit) is not int or not 1 <= limit <= 100 or
                type(max_bytes) is not int or not 1 <= max_bytes <= 262144 or
                (expected_context is not None and (not isinstance(expected_context, str) or re.fullmatch(r'[0-9a-f]{64}', expected_context) is None)) or
                (after > 0 and (upper is None or expected_context is None))):
            raise RetentionError('invalid_retention_plan')
        canonical = lambda value: json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
        policy_row = db.execute('SELECT * FROM security_audit_retention_policies WHERE policy_id=?', (policy_id,)).fetchone()
        if policy_row is None:
            raise RetentionError('retention_policy_not_found')
        policy = dict(policy_row)
        if policy['generation'] != expected_generation:
            raise RetentionError('retention_generation_conflict')
        holds = [dict(row) for row in db.execute('SELECT hold_id,kind,policy_generation FROM security_audit_retention_holds '
            "WHERE policy_id=? AND state='active' ORDER BY hold_id LIMIT 101", (policy_id,)).fetchall()]
        destinations = [dict(row) for row in db.execute('SELECT destination_id,scope_kind,scope_id,generation,state,required_through_sequence '
            'FROM security_audit_destinations WHERE scope_kind=? AND scope_id=? ORDER BY destination_id LIMIT 101',
            (policy['scope_kind'],policy['scope_id'])).fetchall()]
        if len(holds) > 100 or len(destinations) > 100:
            raise RetentionError('retention_plan_context_capacity')
        context = dict(policy=policy,active_holds=holds,destinations=destinations)
        context_sha = hashlib.sha256(canonical(context)).hexdigest()
        if expected_context is not None and expected_context != context_sha:
            raise RetentionError('retention_context_conflict')
        now = int(time.time())
        if not 0 <= now < 2**63:
            raise RetentionError('retention_clock_unavailable')
        current_upper = db.execute('SELECT coalesce(max(sequence),0) FROM security_audit_events '
            'WHERE scope_kind=? AND scope_id=? AND event_kind=?',
            (policy['scope_kind'],policy['scope_id'],policy['event_kind'])).fetchone()[0]
        if upper is None:
            upper = current_upper
        if after > upper or upper > current_upper:
            raise RetentionError('invalid_retention_plan')
        rows = db.execute('SELECT '+','.join(_FIELDS)+' FROM security_audit_events '
            'WHERE scope_kind=? AND scope_id=? AND event_kind=? AND sequence>? AND sequence<=? ORDER BY sequence LIMIT ?',
            (policy['scope_kind'],policy['scope_id'],policy['event_kind'],after,upper,limit+1)).fetchall()
        plan = dict(format_version=1,coverage='business_audit_events_v1',context=context,context_sha256=context_sha,
            observed_at=now,after=after,upper_sequence=upper,items=[],candidate_count=0,blocked_count=0,next_after=None,
            archive_store_validation='not_performed',deletion_authorized=False)
        # Reserve bounded space for counters, cursor and final digest as they grow.
        remaining = max_bytes-len(canonical(plan))-128
        if remaining < 0:
            raise RetentionError('retention_plan_payload_capacity')
        for row in rows[:limit]:
            event = dict(row)
            required = [entry['destination_id'] for entry in destinations if entry['state'] != 'retired'
                        or event['sequence'] <= entry['required_through_sequence']]
            delivered = 0
            if required:
                delivered = db.execute('SELECT count(*) FROM security_audit_delivery WHERE event_id=? '
                    "AND state='delivered' AND destination_id IN ("+','.join('?' for _ in required)+')',
                    (event['event_id'],*required)).fetchone()[0]
            reasons = []
            if policy['state'] != 'active': reasons.append('policy_paused')
            if holds: reasons.append('active_hold')
            if now-event['occurred_at'] < policy['min_age_seconds']: reasons.append('minimum_age')
            if not required: reasons.append('no_required_destination')
            if delivered < len(required): reasons.append('unconfirmed_delivery')
            item = dict(event=event,status='blocked' if reasons else 'candidate',blocked_reasons=reasons,
                        required_destinations=len(required),unconfirmed_destinations=len(required)-delivered)
            size = len(canonical(item))+bool(plan['items'])
            if size > remaining:
                if not plan['items']:
                    raise RetentionError('retention_plan_payload_capacity')
                break
            plan['items'].append(item)
            plan['blocked_count' if reasons else 'candidate_count'] += 1
            remaining -= size
        if len(rows) > len(plan['items']):
            plan['next_after'] = plan['items'][-1]['event']['sequence']
        plan['plan_sha256'] = hashlib.sha256(canonical(plan)).hexdigest()
        if len(canonical(plan)) > max_bytes:
            raise RetentionError('retention_plan_payload_capacity')
        return plan
