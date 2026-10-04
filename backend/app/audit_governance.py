"""Trusted operator destination lifecycle; no tenant or network authority implied."""
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3
import time

from .migrations import MigrationError, _schema, verify


class AuditGovernanceError(RuntimeError):
    pass


@dataclass(frozen=True)
class DestinationReceipt:
    command_id: str
    destination_id: str
    operator_id: str
    action: str
    expected_generation: int
    generation: int
    state: str
    occurred_at: int
    reason: str | None
    required_through_sequence: int | None


def _identifier(value, maximum=100):
    if not isinstance(value, str) or re.fullmatch(r'[A-Za-z0-9_.-]{1,'+str(maximum)+'}', value) is None:
        raise AuditGovernanceError('invalid_audit_governance_request')


class AuditGovernanceRepository:
    def __init__(self, path):
        self.path = Path(path)
        try:
            if verify(self.path) not in (7,9,10,13,14,15,16, 17, 18, 19):
                raise AuditGovernanceError('audit_governance_schema_required')
        except MigrationError:
            raise AuditGovernanceError('audit_governance_schema_required') from None

    @contextmanager
    def _transaction(self, *, read_only=False):
        db = None
        try:
            db = sqlite3.connect(self.path.as_uri()+('?mode=ro' if read_only else '?mode=rw'),
                                 uri=True, timeout=3, isolation_level=None)
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA synchronous=FULL')
            deadline = time.monotonic()+5
            db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            db.execute('BEGIN' if read_only else 'BEGIN IMMEDIATE')
            if _schema(db) not in (7,9,10,13,14,15,16, 17, 18, 19):
                raise AuditGovernanceError('audit_governance_schema_required')
            db.row_factory = sqlite3.Row
            yield db
            db.execute('COMMIT')
        except (sqlite3.Error, OSError, MigrationError):
            raise AuditGovernanceError('audit_governance_unavailable') from None
        finally:
            if db is not None:
                if db.in_transaction:
                    db.rollback()
                db.close()

    def execute(self, *, command_id, operator_id, destination_id, scope_kind, scope_id,
                action, expected_generation, reason=None):
        """Idempotent generation-fenced command under trusted process authority."""
        for value in (command_id, operator_id, scope_id):
            _identifier(value)
        _identifier(destination_id, 64)
        if (scope_kind not in ('account', 'project') or
                action not in ('register', 'suspend', 'resume', 'block', 'retire') or
                type(expected_generation) is not int or not 0 <= expected_generation < 2**63-1 or
                (action == 'block' and reason not in ('receiver_configuration', 'invalid_payload')) or
                (action != 'block' and reason is not None)):
            raise AuditGovernanceError('invalid_audit_governance_request')
        with self._transaction() as db:
            prior = db.execute('SELECT c.*,r.scope_kind,r.scope_id FROM security_audit_destination_commands c '
                'JOIN security_audit_destinations r ON r.destination_id=c.destination_id WHERE c.command_id=?',
                (command_id,)).fetchone()
            if prior:
                keys = ('operator_id', 'destination_id', 'scope_kind', 'scope_id', 'action', 'expected_generation', 'reason')
                if tuple(prior[key] for key in keys) != (operator_id, destination_id, scope_kind, scope_id, action, expected_generation, reason):
                    raise AuditGovernanceError('audit_command_conflict')
                return DestinationReceipt(**{key: prior[key] for key in DestinationReceipt.__dataclass_fields__})
            row = db.execute('SELECT * FROM security_audit_destinations WHERE destination_id=?', (destination_id,)).fetchone()
            now = int(time.time())
            if not 0 <= now < 2**63:
                raise AuditGovernanceError('audit_clock_unavailable')
            through = None
            if action == 'register':
                if expected_generation != 0 or row is not None:
                    raise AuditGovernanceError('audit_generation_conflict')
                table = 'users' if scope_kind == 'account' else 'projects'
                if db.execute('SELECT 1 FROM '+table+' WHERE id=?', (scope_id,)).fetchone() is None:
                    raise AuditGovernanceError('audit_scope_not_found')
                generation, state = 1, 'active'
                db.execute('INSERT INTO security_audit_destinations '
                    '(destination_id,scope_kind,scope_id,generation,state,created_at,updated_at) VALUES (?,?,?,?,?,?,?)',
                    (destination_id, scope_kind, scope_id, generation, state, now, now))
            else:
                if row is None:
                    raise AuditGovernanceError('audit_destination_not_found')
                if (row['scope_kind'], row['scope_id']) != (scope_kind, scope_id):
                    raise AuditGovernanceError('audit_destination_scope_conflict')
                if row['generation'] != expected_generation:
                    raise AuditGovernanceError('audit_generation_conflict')
                allowed = {'suspend': ('active',), 'resume': ('unconfigured', 'paused', 'blocked'),
                           'block': ('active',), 'retire': ('unconfigured', 'active', 'paused', 'blocked')}
                if row['state'] not in allowed[action]:
                    raise AuditGovernanceError('audit_transition_denied')
                generation = expected_generation+1
                state = {'suspend': 'paused', 'resume': 'active', 'block': 'blocked', 'retire': 'retired'}[action]
                now = max(now, row['updated_at'])
                if action == 'retire':
                    unpaid = db.execute('SELECT 1 FROM security_audit_events e WHERE e.scope_kind=? AND e.scope_id=? '
                        'AND NOT EXISTS(SELECT 1 FROM security_audit_delivery d WHERE d.event_id=e.event_id '
                        "AND d.destination_id=? AND d.state='delivered') LIMIT 1",
                        (scope_kind, scope_id, destination_id)).fetchone()
                    if unpaid:
                        raise AuditGovernanceError('audit_outstanding_obligations')
                    through = db.execute('SELECT coalesce(max(sequence),0) FROM security_audit_events '
                        'WHERE scope_kind=? AND scope_id=?', (scope_kind, scope_id)).fetchone()[0]
                db.execute('UPDATE security_audit_destinations SET generation=?,state=?,updated_at=?,blocked_reason=?,blocked_at=?,required_through_sequence=? '
                    'WHERE destination_id=? AND generation=?',
                    (generation, state, now, reason, now if action == 'block' else None, through, destination_id, expected_generation))
            receipt = DestinationReceipt(command_id, destination_id, operator_id, action, expected_generation,
                                         generation, state, now, reason, through)
            db.execute('INSERT INTO security_audit_destination_commands '
                '(command_id,destination_id,operator_id,action,expected_generation,generation,state,occurred_at,reason,required_through_sequence) '
                'VALUES (?,?,?,?,?,?,?,?,?,?)', tuple(receipt.__dict__.values()))
            return receipt

    def page(self, *, after='', limit=50):
        """Read bounded registry identities independent of current process config."""
        if after != '':
            _identifier(after, 64)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise AuditGovernanceError('invalid_audit_governance_request')
        with self._transaction(read_only=True) as db:
            rows = db.execute('SELECT * FROM security_audit_destinations WHERE destination_id>? ORDER BY destination_id LIMIT ?',
                              (after, limit)).fetchall()
            return tuple(dict(row) for row in rows)

    def obligations(self, *, after='', limit=50):
        """One read snapshot of registry-wide debt plus a bounded detail page."""
        if after != '':
            _identifier(after, 64)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise AuditGovernanceError('invalid_audit_governance_request')
        with self._transaction(read_only=True) as db:
            now = int(time.time())
            if not 0 <= now < 2**63:
                raise AuditGovernanceError('audit_clock_unavailable')
            upper = db.execute('SELECT coalesce(max(sequence),0) FROM security_audit_events').fetchone()[0]
            count = db.execute('SELECT count(*) FROM security_audit_destinations').fetchone()[0]
            # This check covers every registered identity, including outside the page.
            unpaid = db.execute('SELECT 1 FROM security_audit_destinations r JOIN security_audit_events e '
                'ON e.scope_kind=r.scope_kind AND e.scope_id=r.scope_id '
                "WHERE e.sequence<=? AND (r.state<>'retired' OR e.sequence<=r.required_through_sequence) "
                'AND NOT EXISTS(SELECT 1 FROM security_audit_delivery d WHERE d.destination_id=r.destination_id '
                "AND d.event_id=e.event_id AND d.state='delivered') LIMIT 1", (upper,)).fetchone()
            rows = db.execute('SELECT * FROM security_audit_destinations WHERE destination_id>? ORDER BY destination_id LIMIT ?',
                              (after, limit+1)).fetchall()
            destinations = []
            for row in rows[:limit]:
                through = min(upper, row['required_through_sequence']) if row['state'] == 'retired' else upper
                counts = db.execute('SELECT count(*) AS required_events,'
                    'coalesce(sum(d.event_id IS NULL),0) AS unenrolled,'
                    "coalesce(sum(d.state='pending'),0) AS pending,"
                    "coalesce(sum(d.state='leased'),0) AS leased,"
                    "coalesce(sum(d.state='delivered'),0) AS delivered,"
                    "coalesce(sum(d.state='leased' AND d.lease_expires_at<=?),0) AS expired_leases,"
                    "min(CASE WHEN d.event_id IS NULL OR d.state<>'delivered' THEN e.occurred_at END) AS oldest_unacked_at,"
                    'max(d.delivered_at) AS last_ack_at '
                    'FROM security_audit_events e LEFT JOIN security_audit_delivery d '
                    'ON d.event_id=e.event_id AND d.destination_id=? '
                    'WHERE e.scope_kind=? AND e.scope_id=? AND e.sequence<=?',
                    (now, row['destination_id'], row['scope_kind'], row['scope_id'], through)).fetchone()
                detail = dict(row) | dict(counts)
                detail['backlog'] = detail['unenrolled']+detail['pending']+detail['leased']
                destinations.append(detail)
            return {'coverage': 'registered_destinations', 'observed_at': now, 'upper_sequence': upper,
                    'registry_count': count, 'registered_drained': count > 0 and unpaid is None,
                    'destinations': tuple(destinations),
                    'next_after': rows[limit-1]['destination_id'] if len(rows) > limit else None}
