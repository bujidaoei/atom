"""Trusted verification-intent ledger, not verifier authentication or execution."""
from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sqlite3
import time

from .migrations import MigrationError, _schema, verify
from .verification_contract import ContractError, VerificationContract, capture_contract, load_contract


class VerificationError(RuntimeError):
    pass


@dataclass(frozen=True)
class VerificationRequest:
    id: str
    workspace_id: str
    project_id: str
    revision_id: str
    contract: VerificationContract
    policy_digest: str
    runner_version: str
    initiator_id: str
    created_at: int
    deadline: int


class VerificationRepository:
    def __init__(self, path: Path, *, lock_timeout: float = 3):
        if isinstance(lock_timeout, bool) or not isinstance(lock_timeout, (float, int)) or not 0 < lock_timeout <= 10:
            raise VerificationError('invalid_verification_configuration')
        self.path, self.timeout = Path(path), lock_timeout
        try:
            if verify(self.path) != 2:
                raise VerificationError('verification_schema_required')
        except MigrationError:
            raise VerificationError('verification_schema_required') from None

    @contextmanager
    def _transaction(self):
        db = None
        try:
            db = sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True, timeout=self.timeout, isolation_level=None)
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            if _schema(db) != 2:
                raise VerificationError('verification_schema_required')
            db.row_factory = sqlite3.Row
            yield db
            db.execute('COMMIT')
        except sqlite3.IntegrityError:
            raise VerificationError('verification_conflict') from None
        except (sqlite3.Error, OSError, MigrationError):
            raise VerificationError('verification_unavailable') from None
        finally:
            if db is not None:
                if db.in_transaction:
                    db.rollback()
                db.close()

    @staticmethod
    def _decode(row):
        try:
            contract = load_contract(row['contract_json'].encode('utf-8'))
        except (ContractError, UnicodeError):
            raise VerificationError('verification_corrupt') from None
        if contract.digest != row['contract_digest']:
            raise VerificationError('verification_corrupt')
        return VerificationRequest(row['id'], row['workspace_id'], row['project_id'], row['revision_id'],
            contract, row['policy_digest'], row['runner_version'], row['initiator_id'], row['created_at'], row['deadline'])

    def reserve(self, *, owner: str, workspace_id: str, request_id: str,
                expected_revision: str, expected_contract: str, policy_digest: str,
                runner_version: str, budget_seconds: int) -> VerificationRequest:
        for value in (owner, workspace_id, request_id, expected_revision, runner_version):
            if not isinstance(value, str) or re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', value) is None:
                raise VerificationError('invalid_verification_request')
        for value in (expected_contract, policy_digest):
            if not isinstance(value, str) or re.fullmatch(r'[0-9a-f]{64}', value) is None:
                raise VerificationError('invalid_verification_request')
        if type(budget_seconds) is not int or not 1 <= budget_seconds <= 900:
            raise VerificationError('invalid_verification_request')
        with self._transaction() as db:
            scope = db.execute('''SELECT w.*,p.active_run_id FROM revision_workspaces w
                JOIN projects p ON p.id=w.project_id WHERE w.id=? AND p.user_id=?''', (workspace_id, owner)).fetchone()
            if scope is None:
                raise VerificationError('verification_not_found')
            previous = db.execute('SELECT * FROM verification_requests WHERE id=?', (request_id,)).fetchone()
            if previous is not None:
                expected = (workspace_id, expected_revision, expected_contract, policy_digest, runner_version, owner, budget_seconds)
                actual = tuple(previous[k] for k in ('workspace_id','revision_id','contract_digest','policy_digest','runner_version','initiator_id')) + (previous['deadline']-previous['created_at'],)
                if expected != actual:
                    raise VerificationError('verification_conflict')
                return self._decode(previous)
            if scope['current_revision_id'] != expected_revision or scope['active_attempt_id'] is not None or scope['active_run_id'] is not None:
                raise VerificationError('verification_conflict')
            rows = db.execute('SELECT key,title,detail,checks_json FROM requirements WHERE project_id=? ORDER BY position,id LIMIT 129', (scope['project_id'],)).fetchall()
            try:
                contract = capture_contract([{'key': r['key'], 'title': r['title'], 'detail': r['detail'],
                    'checks': json.loads(r['checks_json'])} for r in rows])
            except (ContractError, ValueError, TypeError, RecursionError):
                raise VerificationError('invalid_stored_contract') from None
            if contract.digest != expected_contract:
                raise VerificationError('verification_conflict')
            now = int(time.time())
            db.execute('''INSERT INTO verification_requests
                (id,workspace_id,project_id,revision_id,contract_digest,contract_json,policy_digest,runner_version,initiator_id,created_at,deadline)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)''', (request_id,workspace_id,scope['project_id'],expected_revision,
                    contract.digest,contract.canonical.decode('utf-8'),policy_digest,runner_version,owner,now,now+budget_seconds))
            return self._decode(db.execute('SELECT * FROM verification_requests WHERE id=?', (request_id,)).fetchone())
