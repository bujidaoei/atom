"""Owner-scoped, one-use access to an exact registered project revision."""
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re
import secrets
import sqlite3
import time
from uuid import uuid4

from .artifacts import Artifact
from .migrations import MigrationError, _schema, verify


class PreviewAccessError(RuntimeError):
    pass


_IDENTITY = re.compile(r'[A-Za-z0-9_.-]{1,100}\Z')
_SECRET = re.compile(r'[0-9a-f]{64}\Z')


@dataclass(frozen=True)
class PreviewGrant:
    secret: str = field(repr=False)
    expires_at: int
    project_id: str
    revision_id: str


@dataclass(frozen=True)
class PreviewSession:
    secret: str = field(repr=False)
    expires_at: int
    project_id: str
    revision_id: str


@dataclass(frozen=True)
class PreviewRevision:
    project_id: str
    revision_id: str
    owner_id: str
    artifact: Artifact


def _hash(purpose: bytes, secret: str) -> str:
    if type(secret) is not str or _SECRET.fullmatch(secret) is None:
        raise PreviewAccessError('preview_access_denied')
    return hashlib.sha256(b'atom-preview-v1\0' + purpose + b'\0' + bytes.fromhex(secret)).hexdigest()


def _identity(*values: str) -> None:
    if any(type(value) is not str or _IDENTITY.fullmatch(value) is None for value in values):
        raise PreviewAccessError('invalid_preview_request')


class PreviewAccessRepository:
    def __init__(self, path: Path, *, lock_timeout: float = 3):
        if (isinstance(lock_timeout, bool) or not isinstance(lock_timeout, (int, float))
                or not 0 < lock_timeout <= 10):
            raise PreviewAccessError('invalid_preview_configuration')
        self.path, self.timeout = Path(path), lock_timeout
        if not self.path.is_absolute():
            raise PreviewAccessError('invalid_preview_configuration')
        try:
            if verify(self.path) != 18:
                raise PreviewAccessError('preview_schema_required')
        except MigrationError:
            raise PreviewAccessError('preview_schema_required') from None

    @contextmanager
    def _database(self, *, write: bool):
        db = None
        try:
            db = sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True,
                                 isolation_level=None, timeout=self.timeout)
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            db.row_factory = None
            version = _schema(db)
            db.row_factory = sqlite3.Row
            if version != 18:
                raise PreviewAccessError('preview_schema_required')
            yield db
            db.execute('COMMIT')
        except sqlite3.IntegrityError:
            raise PreviewAccessError('preview_conflict') from None
        except (sqlite3.Error, OSError, MigrationError):
            raise PreviewAccessError('preview_unavailable') from None
        finally:
            if db is not None:
                if db.in_transaction:
                    db.rollback()
                db.close()

    @staticmethod
    def _source(db, *, owner_id: str, session_id: str, now: int):
        row = db.execute('SELECT created_at,expires_at,revoked_at FROM console_sessions '
                         'WHERE id=? AND user_id=?', (session_id, owner_id)).fetchone()
        if (row is None or row['revoked_at'] is not None
                or not row['created_at'] <= now < row['expires_at']):
            raise PreviewAccessError('preview_access_denied')
        return row

    @staticmethod
    def _revision(db, *, owner_id: str, project_id: str, revision_id: str,
                  require_selected: bool) -> PreviewRevision:
        row = db.execute('''SELECT r.artifact_key,r.snapshot_revision,a.size FROM revision_records r
            JOIN revision_artifacts a ON a.key=r.artifact_key AND a.revision=r.snapshot_revision
            JOIN projects p ON p.id=r.project_id AND p.user_id=?
            WHERE r.id=? AND r.project_id=?''',
            (owner_id, revision_id, project_id)).fetchone()
        if row is None:
            raise PreviewAccessError('preview_access_denied')
        if require_selected:
            selected = db.execute('''SELECT 1 FROM revision_workspaces w
                WHERE w.project_id=? AND w.current_revision_id=?
                UNION ALL SELECT 1 FROM release_records r
                WHERE r.project_id=? AND r.revision_id=? LIMIT 1''',
                (project_id, revision_id, project_id, revision_id)).fetchone()
            if selected is None:
                raise PreviewAccessError('preview_access_denied')
        return PreviewRevision(project_id, revision_id, owner_id,
                               Artifact(row['artifact_key'], row['snapshot_revision'], row['size']))

    def issue(self, *, owner_id: str, source_session_id: str,
              project_id: str, revision_id: str) -> PreviewGrant:
        _identity(owner_id, source_session_id, project_id, revision_id)
        with self._database(write=True) as db:
            now = int(time.time())
            source = self._source(db, owner_id=owner_id, session_id=source_session_id, now=now)
            if db.execute("SELECT 1 FROM project_origin_ports WHERE project_id=? AND purpose='preview'",
                          (project_id,)).fetchone() is None:
                raise PreviewAccessError('preview_origin_required')
            self._revision(db, owner_id=owner_id, project_id=project_id,
                           revision_id=revision_id, require_selected=True)
            db.execute('DELETE FROM preview_sessions WHERE expires_at<=?', (now,))
            db.execute('DELETE FROM preview_handoffs WHERE expires_at<=?', (now,))
            active = db.execute('''SELECT count(*) FROM preview_handoffs
                WHERE project_id=? AND owner_id=? AND consumed_at IS NULL AND expires_at>?''',
                (project_id, owner_id, now)).fetchone()[0]
            if active >= 32:
                raise PreviewAccessError('preview_capacity')
            expires = min(now + 60, source['expires_at'])
            if expires <= now:
                raise PreviewAccessError('preview_access_denied')
            secret = secrets.token_hex(32)
            db.execute('INSERT INTO preview_handoffs VALUES (?,?,?,?,?,?,?,NULL)',
                       (_hash(b'handoff', secret), project_id, revision_id,
                        owner_id, source_session_id, now, expires))
            db.execute('INSERT INTO preview_audit_events '
                       '(event_id,event_kind,project_id,revision_id,owner_id,source_session_id,occurred_at) '
                       'VALUES (?,?,?,?,?,?,?)',
                       (uuid4().hex, 'preview.handoff.issued', project_id,
                        revision_id, owner_id, source_session_id, now))
            return PreviewGrant(secret, expires, project_id, revision_id)

    def exchange(self, *, project_id: str, handoff: str) -> PreviewSession:
        _identity(project_id)
        digest = _hash(b'handoff', handoff)
        with self._database(write=True) as db:
            now = int(time.time())
            row = db.execute('SELECT * FROM preview_handoffs WHERE token_hash=? AND project_id=?',
                             (digest, project_id)).fetchone()
            if (row is None or row['consumed_at'] is not None
                    or not row['created_at'] <= now < row['expires_at']):
                raise PreviewAccessError('preview_access_denied')
            source = self._source(db, owner_id=row['owner_id'],
                                  session_id=row['source_session_id'], now=now)
            self._revision(db, owner_id=row['owner_id'], project_id=project_id,
                           revision_id=row['revision_id'], require_selected=False)
            count = db.execute('''SELECT count(*) FROM preview_sessions
                WHERE project_id=? AND owner_id=? AND revoked_at IS NULL AND expires_at>?''',
                (project_id, row['owner_id'], now)).fetchone()[0]
            if count >= 8:
                raise PreviewAccessError('preview_capacity')
            expires = min(now + 900, source['expires_at'])
            if expires <= now:
                raise PreviewAccessError('preview_access_denied')
            secret = secrets.token_hex(32)
            db.execute('UPDATE preview_handoffs SET consumed_at=? WHERE token_hash=?', (now, digest))
            db.execute('INSERT INTO preview_sessions VALUES (?,?,?,?,?,?,?,?,NULL)',
                       (_hash(b'session', secret), digest, project_id, row['revision_id'],
                        row['owner_id'], row['source_session_id'], now, expires))
            db.execute('INSERT INTO preview_audit_events '
                       '(event_id,event_kind,project_id,revision_id,owner_id,source_session_id,occurred_at) '
                       'VALUES (?,?,?,?,?,?,?)',
                       (uuid4().hex, 'preview.session.created', project_id,
                        row['revision_id'], row['owner_id'], row['source_session_id'], now))
            return PreviewSession(secret, expires, project_id, row['revision_id'])

    def authorize(self, *, project_id: str, session_secret: str) -> PreviewRevision:
        _identity(project_id)
        digest = _hash(b'session', session_secret)
        with self._database(write=False) as db:
            now = int(time.time())
            row = db.execute('SELECT * FROM preview_sessions WHERE token_hash=? AND project_id=?',
                             (digest, project_id)).fetchone()
            if (row is None or row['revoked_at'] is not None
                    or not row['created_at'] <= now < row['expires_at']):
                raise PreviewAccessError('preview_access_denied')
            self._source(db, owner_id=row['owner_id'],
                         session_id=row['source_session_id'], now=now)
            return self._revision(db, owner_id=row['owner_id'], project_id=project_id,
                                  revision_id=row['revision_id'], require_selected=False)
