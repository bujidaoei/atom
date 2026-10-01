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


_FIELDS = ('sequence','event_id','schema_version','event_kind','occurred_at','actor_kind','actor_id',
           'scope_kind','scope_id','operation_id','source_session_id','binding_id','release_id',
           'revision_id','publication_generation','affected_count')


class AuditRepository:
    def __init__(self, path: Path):
        self.path = Path(path)
        try:
            if verify(self.path) not in (5,6,7,9):
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
            if _schema(db) not in (5,6,7,9):
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
