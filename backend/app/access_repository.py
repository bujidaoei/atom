"""Durable access ledger. Callers must authenticate before creating sessions."""
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import re
import secrets
import sqlite3
import time

from .migrations import MigrationError, _schema, verify


class AccessError(RuntimeError):
    pass


@dataclass(frozen=True)
class ConsoleSession:
    id: str
    user_id: str
    created_at: int
    expires_at: int
    revoked_at: int | None


class AccessRepository:
    def __init__(self, path: Path, *, lock_timeout: float = 3, active_sessions_per_user: int = 16):
        if (isinstance(lock_timeout,bool) or not isinstance(lock_timeout,(int,float)) or not 0<lock_timeout<=10
                or type(active_sessions_per_user) is not int or not 1<=active_sessions_per_user<=128):
            raise AccessError('invalid_access_configuration')
        self.path, self.timeout = Path(path), lock_timeout
        self.active_sessions_per_user = active_sessions_per_user
        try:
            if verify(self.path)!=4:
                raise AccessError('access_schema_required')
        except MigrationError:
            raise AccessError('access_schema_required') from None

    @contextmanager
    def _transaction(self):
        db=None
        try:
            db=sqlite3.connect(self.path.as_uri()+'?mode=rw',uri=True,timeout=self.timeout,isolation_level=None)
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            if _schema(db)!=4:
                raise AccessError('access_schema_required')
            db.row_factory=sqlite3.Row
            yield db
            db.execute('COMMIT')
        except sqlite3.IntegrityError:
            raise AccessError('access_conflict') from None
        except (sqlite3.Error,OSError,MigrationError):
            raise AccessError('access_unavailable') from None
        finally:
            if db is not None:
                if db.in_transaction:db.rollback()
                db.close()

    @staticmethod
    def _user(user_id):
        if not isinstance(user_id,str) or re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',user_id) is None:
            raise AccessError('session_not_found')

    @staticmethod
    def _identity(session_id):
        if not isinstance(session_id,str) or re.fullmatch(r'[0-9a-f]{32}',session_id) is None:
            raise AccessError('session_not_found')

    @staticmethod
    def _decode(row):
        return ConsoleSession(*(row[key] for key in ('id','user_id','created_at','expires_at','revoked_at')))

    def create_console_session(self, *, user_id: str, lifetime_seconds: int) -> ConsoleSession:
        """For a trusted authenticated caller; a session ID is not a bearer token."""
        self._user(user_id)
        if type(lifetime_seconds) is not int or not 1<=lifetime_seconds<=90*86400:
            raise AccessError('invalid_session_lifetime')
        with self._transaction() as db:
            now=int(time.time())
            if not 0<=now<2**63-90*86400:
                raise AccessError('invalid_access_clock')
            if db.execute('SELECT 1 FROM users WHERE id=?',(user_id,)).fetchone() is None:
                raise AccessError('session_not_found')
            active=db.execute('SELECT id FROM console_sessions WHERE user_id=? AND revoked_at IS NULL AND expires_at>? LIMIT ?',
                              (user_id,now,self.active_sessions_per_user)).fetchall()
            if len(active)>=self.active_sessions_per_user:
                raise AccessError('session_capacity')
            result=ConsoleSession(secrets.token_hex(16),user_id,now,now+lifetime_seconds,None)
            db.execute('INSERT INTO console_sessions VALUES (?,?,?,?,NULL)',
                       (result.id,user_id,result.created_at,result.expires_at))
            return result

    def console_session(self, *, user_id: str, session_id: str) -> ConsoleSession:
        """Check persisted scope after the caller verifies the signed credential."""
        self._user(user_id);self._identity(session_id)
        with self._transaction() as db:
            row=db.execute('SELECT * FROM console_sessions WHERE id=? AND user_id=?',(session_id,user_id)).fetchone()
            now=int(time.time())
            if row is None or row['revoked_at'] is not None or not row['created_at']<=now<row['expires_at']:
                raise AccessError('session_not_found')
            return self._decode(row)

    def revoke_console_session(self, *, user_id: str, session_id: str) -> ConsoleSession:
        self._user(user_id);self._identity(session_id)
        with self._transaction() as db:
            row=db.execute('SELECT * FROM console_sessions WHERE id=? AND user_id=?',(session_id,user_id)).fetchone()
            if row is None:
                raise AccessError('session_not_found')
            if row['revoked_at'] is not None:
                return self._decode(row)
            now=int(time.time())
            if now<row['created_at']:
                raise AccessError('invalid_access_clock')
            db.execute('UPDATE console_sessions SET revoked_at=? WHERE id=?',(now,session_id))
            return self._decode(db.execute('SELECT * FROM console_sessions WHERE id=?',(session_id,)).fetchone())
