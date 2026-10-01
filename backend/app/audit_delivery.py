"""Durable delivery state for trusted operators; no network or caller authorization API."""
from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import re
import secrets
import sqlite3
import time

from .audit_repository import _FIELDS
from .migrations import MigrationError, _schema, verify


class AuditDeliveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class DeliveryLease:
    owner: str
    expires_at: int
    events: tuple[dict, ...]


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise AuditDeliveryError('invalid_delivery_bounds')


class AuditDeliveryRepository:
    def __init__(self, path, *, destination_id, scope_kind, scope_id):
        if (not isinstance(destination_id, str) or
                re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', destination_id) is None or
                scope_kind not in ('account', 'project') or not isinstance(scope_id, str) or
                re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', scope_id) is None):
            raise AuditDeliveryError('invalid_delivery_scope')
        self.path = Path(path)
        self.destination_id, self.scope_kind, self.scope_id = destination_id, scope_kind, scope_id
        try:
            if verify(self.path) != 5:
                raise AuditDeliveryError('audit_schema_required')
        except MigrationError:
            raise AuditDeliveryError('audit_schema_required') from None

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
            if _schema(db) != 5:
                raise AuditDeliveryError('audit_schema_required')
            conflicting = db.execute('SELECT 1 FROM security_audit_delivery d '
                'JOIN security_audit_events e ON e.event_id=d.event_id WHERE d.destination_id=? '
                'AND (e.scope_kind<>? OR e.scope_id<>?) LIMIT 1',
                (self.destination_id, self.scope_kind, self.scope_id)).fetchone()
            if conflicting:
                raise AuditDeliveryError('destination_scope_conflict')
            yield db
            db.execute('COMMIT')
        except (sqlite3.Error, OSError, MigrationError):
            raise AuditDeliveryError('audit_delivery_unavailable') from None
        finally:
            if db is not None:
                if db.in_transaction:
                    db.rollback()
                db.close()

    @staticmethod
    def _now():
        now = int(time.time())
        _integer(now, 0, 2**63-601)
        return now

    def enroll(self, *, limit=100, max_outstanding=10000):
        """Add committed scoped events; capacity leaves remaining events in the ledger."""
        _integer(limit, 1, 100)
        _integer(max_outstanding, 1, 10000)
        with self._transaction() as db:
            now = self._now()
            outstanding = len(db.execute('SELECT 1 FROM security_audit_delivery '
                "WHERE destination_id=? AND state<>'delivered' LIMIT ?",
                (self.destination_id, max_outstanding+1)).fetchall())
            take = min(limit, max(0, max_outstanding-outstanding))
            rows = db.execute('SELECT e.event_id FROM security_audit_events e '
                'WHERE e.scope_kind=? AND e.scope_id=? AND NOT EXISTS '
                '(SELECT 1 FROM security_audit_delivery d WHERE d.destination_id=? AND d.event_id=e.event_id) '
                'ORDER BY e.sequence LIMIT ?',
                (self.scope_kind, self.scope_id, self.destination_id, take+1)).fetchall()
            for event_id, in rows[:take]:
                db.execute('INSERT INTO security_audit_delivery '
                    '(event_id,destination_id,state,next_attempt_at) VALUES (?,?,?,?)',
                    (event_id, self.destination_id, 'pending', now))
            added = min(len(rows), take)
            return {'added': added, 'remaining': len(rows)>take,
                    'capacity_reached': outstanding+added >= max_outstanding}

    def claim(self, *, limit=100, lease_seconds=30, max_bytes=262144):
        _integer(limit, 1, 100)
        _integer(lease_seconds, 1, 300)
        _integer(max_bytes, 2, 262144)
        with self._transaction() as db:
            now = self._now()
            owner = secrets.token_hex(16)
            rows = db.execute('SELECT '+','.join('e.'+key for key in _FIELDS)+
                ' FROM security_audit_delivery d JOIN security_audit_events e ON e.event_id=d.event_id '
                "WHERE d.destination_id=? AND ((d.state='pending' AND d.next_attempt_at<=?) OR "
                "(d.state='leased' AND d.lease_expires_at<=?)) ORDER BY e.sequence LIMIT ?",
                (self.destination_id, now, now, limit)).fetchall()
            events = []
            size = 2  # Compact UTF-8 JSON array including brackets and separators.
            for row in rows:
                event = dict(zip(_FIELDS, row))
                extra = len(json.dumps(event, ensure_ascii=True, separators=(',', ':')).encode('utf-8'))
                extra += bool(events)
                if size+extra > max_bytes:
                    if not events:
                        raise AuditDeliveryError('audit_payload_capacity')
                    break
                events.append(event)
                size += extra
            for event in events:
                db.execute("UPDATE security_audit_delivery SET state='leased',attempt=attempt+1,"
                    'lease_owner=?,lease_expires_at=? WHERE destination_id=? AND event_id=?',
                    (owner, now+lease_seconds, self.destination_id, event['event_id']))
            return DeliveryLease(owner, now+lease_seconds, tuple(events))

    @staticmethod
    def _batch(event_ids, lease_owner):
        if (not isinstance(event_ids, (list, tuple)) or not 1 <= len(event_ids) <= 100 or
                any(not isinstance(value, str) or re.fullmatch(r'[0-9a-f]{32}', value) is None for value in event_ids) or
                len(set(event_ids)) != len(event_ids) or not isinstance(lease_owner, str) or
                re.fullmatch(r'[0-9a-f]{32}', lease_owner) is None):
            raise AuditDeliveryError('invalid_delivery_batch')

    def _settle(self, *, event_ids, lease_owner, delivered):
        self._batch(event_ids, lease_owner)
        with self._transaction() as db:
            now = self._now()
            placeholders = ','.join('?' for _ in event_ids)
            rows = db.execute('SELECT event_id,attempt FROM security_audit_delivery WHERE destination_id=? '
                "AND state='leased' AND lease_owner=? AND lease_expires_at>? AND event_id IN ("+placeholders+')',
                (self.destination_id, lease_owner, now, *event_ids)).fetchall()
            if len(rows) != len(event_ids):
                raise AuditDeliveryError('audit_lease_conflict')
            for event_id, attempt in rows:
                if delivered:
                    db.execute("UPDATE security_audit_delivery SET state='delivered',delivered_at=?,"
                        'lease_owner=NULL,lease_expires_at=NULL WHERE destination_id=? AND event_id=?',
                        (now, self.destination_id, event_id))
                else:
                    delay = min(300, 2**min(attempt, 9))
                    db.execute("UPDATE security_audit_delivery SET state='pending',next_attempt_at=?,"
                        'lease_owner=NULL,lease_expires_at=NULL WHERE destination_id=? AND event_id=?',
                        (now+delay, self.destination_id, event_id))

    def acknowledge(self, *, event_ids, lease_owner):
        """Trusted sender calls only after actual receiver acknowledgement."""
        self._settle(event_ids=event_ids, lease_owner=lease_owner, delivered=True)

    def retry(self, *, event_ids, lease_owner):
        self._settle(event_ids=event_ids, lease_owner=lease_owner, delivered=False)

    def status(self):
        with self._transaction(read_only=True) as db:
            now = self._now()
            rows = db.execute('SELECT state,count(*) FROM security_audit_delivery '
                'WHERE destination_id=? GROUP BY state', (self.destination_id,)).fetchall()
            result = dict.fromkeys(('pending', 'leased', 'delivered'), 0)
            result.update(rows)
            result['expired_leases'] = db.execute('SELECT count(*) FROM security_audit_delivery '
                "WHERE destination_id=? AND state='leased' AND lease_expires_at<=?",
                (self.destination_id, now)).fetchone()[0]
            result['oldest_unacked_at'], result['last_ack_at'] = db.execute(
                "SELECT min(CASE WHEN d.state<>'delivered' THEN e.occurred_at END),max(d.delivered_at) "
                'FROM security_audit_delivery d JOIN security_audit_events e ON e.event_id=d.event_id '
                'WHERE d.destination_id=?', (self.destination_id,)).fetchone()
            result['unenrolled'], result['oldest_unenrolled_at'] = db.execute(
                'SELECT count(*),min(e.occurred_at) FROM security_audit_events e '
                'WHERE e.scope_kind=? AND e.scope_id=? AND NOT EXISTS '
                '(SELECT 1 FROM security_audit_delivery d WHERE d.destination_id=? AND d.event_id=e.event_id)',
                (self.scope_kind, self.scope_id, self.destination_id)).fetchone()
            times = [value for value in (result['oldest_unacked_at'], result['oldest_unenrolled_at']) if value is not None]
            result['oldest_unacked_at'] = min(times) if times else None
            result['backlog'] = result['pending']+result['leased']+result['unenrolled']
            result['observed_at'] = now
            return result
