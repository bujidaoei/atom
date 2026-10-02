"""Bounded audit reads for a caller whose signed source was already authenticated."""
from dataclasses import dataclass
from pathlib import Path
import sqlite3
import time

from .access_repository import AccessRepository, AccessError
from .migrations import MigrationError, _schema, verify


class AuditReadError(RuntimeError):
    pass


@dataclass(frozen=True)
class AuditPage:
    events: tuple[dict, ...]
    upper: int
    next_after: int | None
    archived: tuple[dict, ...] = ()


from .audit_event_format import EVENT_FIELDS as _FIELDS


class AuditRepository:
    def __init__(self, path: Path):
        self.path = Path(path)
        try:
            if verify(self.path) not in (5,6,7,9,10,11,12,13,14,15,16, 17, 18):
                raise AuditReadError('audit_schema_required')
        except MigrationError:
            raise AuditReadError('audit_schema_required') from None

    def page(self, *, user_id, source_session_id, project_id=None, after=0, upper=None, limit=50):
        """Reauthorize the source and scope within the same read snapshot as the rows."""
        try:
            AccessRepository._user(user_id)
            AccessRepository._identity(source_session_id)
            if project_id is not None:
                AccessRepository._user(project_id)
        except AccessError:
            raise AuditReadError('audit_access_denied') from None
        if (type(after) is not int or not 0 <= after < 2**63 or
                type(limit) is not int or not 1 <= limit <= 100 or
                (upper is not None and (type(upper) is not int or not after <= upper < 2**63))):
            raise AuditReadError('invalid_audit_page')
        db = None
        try:
            db = sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True,timeout=3,isolation_level=None)
            deadline = time.monotonic()+5
            db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            db.execute('BEGIN')
            version = _schema(db)
            if version not in (5,6,7,9,10,11,12,13,14,15,16, 17, 18):
                raise AuditReadError('audit_schema_required')
            now = int(time.time())
            source = db.execute('SELECT 1 FROM console_sessions WHERE id=? AND user_id=? '
                'AND revoked_at IS NULL AND created_at<=? AND expires_at>?',
                (source_session_id,user_id,now,now)).fetchone()
            if source is None:
                raise AuditReadError('audit_access_denied')
            scope_kind, scope_id = 'account', user_id
            if project_id is not None:
                if db.execute('SELECT 1 FROM projects WHERE id=? AND user_id=?',(project_id,user_id)).fetchone() is None:
                    raise AuditReadError('audit_access_denied')
                scope_kind, scope_id = 'project', project_id
            if version in (11,12,13,14,15,16, 17, 18):
                return self._archived_page(db, scope_kind, scope_id, after, upper, limit)
            if upper is None:
                upper = db.execute('SELECT coalesce(max(sequence),0) FROM security_audit_events '
                    'WHERE scope_kind=? AND scope_id=?',(scope_kind,scope_id)).fetchone()[0]
                if after > upper:
                    raise AuditReadError('invalid_audit_page')
            rows = db.execute('SELECT '+','.join(_FIELDS)+' FROM security_audit_events '
                'WHERE scope_kind=? AND scope_id=? AND sequence>? AND sequence<=? ORDER BY sequence LIMIT ?',
                (scope_kind,scope_id,after,upper,limit+1)).fetchall()
            items = tuple(dict(zip(_FIELDS,row)) for row in rows[:limit])
            return AuditPage(items, upper, items[-1]['sequence'] if len(rows)>limit else None)
        except (sqlite3.Error, OSError, MigrationError):
            raise AuditReadError('audit_unavailable') from None
        finally:
            if db is not None:
                if db.in_transaction: db.rollback()
                db.close()

    @staticmethod
    def _archived_page(db, scope_kind, scope_id, after, upper, limit):
        """One sequence window across payloads and archived identities in this snapshot."""
        scope = (scope_kind, scope_id)
        if upper is None:
            upper = db.execute(
                'SELECT max(value) FROM ('
                'SELECT coalesce(max(sequence),0) AS value FROM security_audit_events WHERE scope_kind=? AND scope_id=? '
                'UNION ALL SELECT coalesce(max(sequence),0) FROM security_audit_archived_events WHERE scope_kind=? AND scope_id=?)',
                scope + scope).fetchone()[0]
            if after > upper:
                raise AuditReadError('invalid_audit_page')
        window = scope + (after, upper)
        rows = db.execute(
            'SELECT sequence,archived FROM ('
            'SELECT sequence,0 AS archived FROM security_audit_events WHERE scope_kind=? AND scope_id=? AND sequence>? AND sequence<=? '
            'UNION ALL SELECT sequence,1 FROM security_audit_archived_events WHERE scope_kind=? AND scope_id=? AND sequence>? AND sequence<=?) '
            'ORDER BY sequence LIMIT ?', window + window + (limit + 1,)).fetchall()
        selected = rows[:limit]
        live_ids = tuple(sequence for sequence, archived in selected if not archived)
        archived_ids = tuple(sequence for sequence, archived in selected if archived)
        events = ()
        archived = ()
        if live_ids:
            values = db.execute('SELECT '+','.join(_FIELDS)+' FROM security_audit_events WHERE sequence IN ('+
                                ','.join('?' for _ in live_ids)+') ORDER BY sequence', live_ids).fetchall()
            events = tuple(dict(zip(_FIELDS, row)) for row in values)
        if archived_ids:
            fields = ('sequence','event_id','scope_kind','scope_id','event_kind','command_id','archive_id','recovery_id','archived_at')
            values = db.execute(
                'SELECT m.sequence,m.event_id,m.scope_kind,m.scope_id,m.event_kind,m.command_id,r.archive_id,r.recovery_id,r.occurred_at '
                'FROM security_audit_archived_events m JOIN security_audit_prune_receipts r ON r.command_id=m.command_id '
                'WHERE m.sequence IN ('+','.join('?' for _ in archived_ids)+') ORDER BY m.sequence', archived_ids).fetchall()
            archived = tuple(dict(zip(fields, row)) for row in values)
        return AuditPage(events, upper, selected[-1][0] if len(rows)>limit else None, archived)
