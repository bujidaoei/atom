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
    def __init__(self, path):
        self.path = Path(path)
        try:
            if verify(self.path) != 8:
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
            if _schema(db) != 8:
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
