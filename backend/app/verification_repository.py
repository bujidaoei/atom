"""Trusted verification-intent ledger, not verifier authentication or execution."""
from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sqlite3
import time

from .migrations import MigrationError, _schema, verify
from .verification_contract import ContractError, VerificationContract, capture_contract, capture_report, load_contract


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


@dataclass(frozen=True)
class VerificationResult:
    request_id: str
    revision_id: str
    contract_digest: str
    outcome: str
    total: int
    passed: int
    report: bytes
    completed_at: int


class VerificationRepository:
    def __init__(self, path: Path, *, lock_timeout: float = 3):
        if isinstance(lock_timeout, bool) or not isinstance(lock_timeout, (float, int)) or not 0 < lock_timeout <= 10:
            raise VerificationError('invalid_verification_configuration')
        self.path, self.timeout = Path(path), lock_timeout
        try:
            if verify(self.path) not in (2, 3, 4, 5, 6, 7):
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
            if _schema(db) not in (2, 3, 4, 5, 6, 7):
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

    def record_report(self, *, owner: str, request_id: str, results) -> VerificationResult:
        """Called only by a trusted verifier coordinator after authentication.

        Owner scoping is not proof that a browser ran. No public route exposes
        this method. Historical evidence must be rechecked by release policy.
        """
        if any(not isinstance(value, str) or re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', value) is None
               for value in (owner, request_id)):
            raise VerificationError('invalid_verification_request')
        with self._transaction() as db:
            row = db.execute('''SELECT v.* FROM verification_requests v
                JOIN projects p ON p.id=v.project_id WHERE v.id=? AND p.user_id=?''',
                (request_id, owner)).fetchone()
            if row is None:
                raise VerificationError('verification_not_found')
            request = self._decode(row)
            try:
                report = capture_report(request.contract, results)
            except ContractError:
                raise VerificationError('invalid_verification_report') from None
            canonical = report.canonical.decode('utf-8')
            previous = db.execute('SELECT * FROM verification_results WHERE request_id=?', (request_id,)).fetchone()
            outcome = 'passed' if report.passed == report.total else 'failed'
            if previous is not None:
                if (previous['report_json'],previous['outcome'],previous['total'],previous['passed']) != (
                        canonical,outcome,report.total,report.passed):
                    raise VerificationError('verification_conflict')
                completed_at = previous['completed_at']
            else:
                completed_at = int(time.time())
                if not request.created_at <= completed_at <= request.deadline:
                    raise VerificationError('verification_expired')
                db.execute('''INSERT INTO verification_results
                    (request_id,workspace_id,revision_id,contract_digest,policy_digest,outcome,total,passed,report_json,completed_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)''', (request.id,request.workspace_id,request.revision_id,
                        request.contract.digest,request.policy_digest,outcome,report.total,report.passed,canonical,completed_at))
            return VerificationResult(request_id,request.revision_id,request.contract.digest,outcome,
                                      report.total,report.passed,report.canonical,completed_at)

    def terminate(self, *, owner: str, request_id: str, outcome: str) -> VerificationResult:
        """Persist interruption without inventing per-check observations."""
        if outcome not in ('cancelled', 'timed_out') or any(
            not isinstance(value, str) or re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', value) is None
            for value in (owner, request_id)
        ):
            raise VerificationError('invalid_verification_request')
        with self._transaction() as db:
            row = db.execute('''SELECT v.* FROM verification_requests v
                JOIN projects p ON p.id=v.project_id WHERE v.id=? AND p.user_id=?''', (request_id,owner)).fetchone()
            if row is None:
                raise VerificationError('verification_not_found')
            request = self._decode(row)
            previous = db.execute('SELECT * FROM verification_results WHERE request_id=?', (request_id,)).fetchone()
            if previous is not None:
                if previous['outcome'] != outcome:
                    raise VerificationError('verification_conflict')
                return VerificationResult(request_id,request.revision_id,request.contract.digest,outcome,
                    previous['total'],previous['passed'],previous['report_json'].encode('utf-8'),previous['completed_at'])
            now = int(time.time())
            if now < request.created_at or (outcome == 'timed_out' and now <= request.deadline):
                raise VerificationError('verification_not_expired')
            # Interrupted reports explicitly omit check observations. Zero passed
            # is not a claim that every check executed and failed.
            report = json.dumps({'format':'atom-verification-interruption-v1',
                'contractDigest':request.contract.digest,'outcome':outcome},sort_keys=True,separators=(',',':'))
            total = len(request.contract.checks)
            db.execute('''INSERT INTO verification_results
                (request_id,workspace_id,revision_id,contract_digest,policy_digest,outcome,total,passed,report_json,completed_at)
                VALUES (?,?,?,?,?,?,?,0,?,?)''', (request_id,request.workspace_id,request.revision_id,
                    request.contract.digest,request.policy_digest,outcome,total,report,now))
            return VerificationResult(request_id,request.revision_id,request.contract.digest,outcome,total,0,report.encode('utf-8'),now)

    def expired(self, *, limit: int = 100) -> tuple[tuple[str, str], ...]:
        """Trusted recovery inventory; returns owner/request IDs, not authority."""
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise VerificationError('invalid_verification_request')
        with self._transaction() as db:
            rows = db.execute('''SELECT p.user_id,v.id FROM verification_requests v
                JOIN projects p ON p.id=v.project_id LEFT JOIN verification_results r ON r.request_id=v.id
                WHERE r.request_id IS NULL AND v.deadline<? ORDER BY v.deadline,v.id LIMIT ?''',
                (int(time.time()),limit+1)).fetchall()
            if len(rows) > limit:
                raise VerificationError('verification_recovery_capacity')
            return tuple((row[0],row[1]) for row in rows)
