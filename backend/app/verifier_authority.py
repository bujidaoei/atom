"""Offline v13 verifier dispatch and one-use report registration.

The trusted coordinator owns dispatch. A separate worker receives only the
returned credential and pinned identities; no HTTP route exposes this class.
Process isolation and proof that route_id serves those bytes remain separate.
"""
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import re
import secrets
import time

from .artifacts import Artifact
from .migrations import MigrationError, verify
from .verification_contract import ContractError, capture_contract, capture_report
from .verification_repository import VerificationError, VerificationRepository, VerificationRequest, VerificationResult


_ID = re.compile(r'[A-Za-z0-9_.-]{1,128}\Z')
_DIGEST = re.compile(r'[0-9a-f]{64}\Z')
_ROUTE = re.compile(r'[0-9a-f]{32}\Z')
_MISSING_DIGEST = bytes(32)


def _matches(pattern, value):
    return type(value) is str and pattern.fullmatch(value) is not None


def _contract(db, project_id):
    rows = db.execute('''SELECT key,title,detail,checks_json FROM requirements
        WHERE project_id=? ORDER BY position,id LIMIT 129''', (project_id,)).fetchall()
    try:
        return capture_contract([{'key': row['key'], 'title': row['title'], 'detail': row['detail'],
            'checks': json.loads(row['checks_json'])} for row in rows])
    except (ContractError, ValueError, TypeError, RecursionError):
        raise VerificationError('invalid_stored_contract') from None


@dataclass(frozen=True)
class VerifierAssignment:
    request: VerificationRequest
    artifact: Artifact
    route_id: str
    verifier_id: str
    environment_digest: str
    credential: bytes = field(repr=False)


class VerifierAuthority:
    def __init__(self, path, *, lock_timeout=3):
        try:
            if verify(path) != 13:
                raise VerificationError('verifier_schema_required')
        except MigrationError:
            raise VerificationError('verifier_schema_required') from None
        self._ledger = VerificationRepository(path, lock_timeout=lock_timeout)

    def dispatch(self, *, owner: str, request_id: str, artifact: Artifact,
                 route_id: str, verifier_id: str, environment_digest: str) -> VerifierAssignment:
        return self._dispatch(owner=owner, request_id=request_id, artifact=artifact,
                              route_id=route_id, verifier_id=verifier_id,
                              environment_digest=environment_digest)

    def dispatch_current(self, *, owner: str, request_id: str, route_id: str,
                         verifier_id: str, environment_digest: str) -> VerifierAssignment:
        """Derive the exact artifact under the dispatch transaction, never from HTTP input."""
        return self._dispatch(owner=owner, request_id=request_id, artifact=None,
                              route_id=route_id, verifier_id=verifier_id,
                              environment_digest=environment_digest)

    def _dispatch(self, *, owner: str, request_id: str, artifact: Artifact | None,
                  route_id: str, verifier_id: str, environment_digest: str) -> VerifierAssignment:
        if (not all(_matches(_ID, value) for value in (owner, request_id, verifier_id))
                or not _matches(_ROUTE, route_id) or not _matches(_DIGEST, environment_digest)
                or (artifact is not None and type(artifact) is not Artifact)):
            raise VerificationError('invalid_verifier_dispatch')
        with self._ledger._transaction() as db:
            if db.execute('PRAGMA user_version').fetchone()[0] != 13:
                raise VerificationError('verifier_schema_required')
            row = db.execute('''SELECT q.* FROM verification_requests q
                JOIN projects p ON p.id=q.project_id AND p.user_id=?
                WHERE q.id=?''', (owner, request_id)).fetchone()
            if row is None:
                raise VerificationError('verification_not_found')
            request = self._ledger._decode(row)
            previous = db.execute('SELECT 1 FROM verification_dispatches WHERE request_id=?',
                                  (request_id,)).fetchone()
            if previous is not None:
                # A credential is never returned again; recovery must query the
                # result or expire this attempt, not issue parallel authority.
                raise VerificationError('verifier_already_dispatched')
            now = int(time.time())
            if not request.created_at <= now < request.deadline:
                raise VerificationError('verification_expired')
            if _contract(db, request.project_id).digest != request.contract.digest:
                raise VerificationError('verification_stale_contract')
            descriptor = db.execute('''SELECT a.key,a.revision,a.size FROM revision_records r
                JOIN revision_artifacts a ON a.key=r.artifact_key AND a.revision=r.snapshot_revision
                JOIN revision_workspaces w ON w.id=r.workspace_id
                JOIN projects p ON p.id=r.project_id
                WHERE r.id=? AND r.workspace_id=? AND r.project_id=?
                  AND w.current_revision_id=r.id AND w.active_attempt_id IS NULL
                  AND p.active_run_id IS NULL AND p.status='ready' ''',
                (request.revision_id, request.workspace_id, request.project_id)).fetchone()
            if descriptor is None:
                raise VerificationError('verification_stale_artifact')
            current_artifact = Artifact(*descriptor)
            if artifact is not None and artifact != current_artifact:
                raise VerificationError('verification_stale_artifact')
            artifact = current_artifact
            issued_at = int(time.time())
            if not request.created_at <= issued_at < request.deadline:
                raise VerificationError('verification_expired')
            credential = secrets.token_bytes(32)
            db.execute('''INSERT INTO verification_dispatches
                (request_id,project_id,workspace_id,revision_id,contract_digest,policy_digest,
                 runner_version,artifact_key,snapshot_revision,artifact_size,route_id,verifier_id,
                 environment_digest,credential_digest,issued_at,deadline)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (request.id,request.project_id,request.workspace_id,request.revision_id,
                 request.contract.digest,request.policy_digest,request.runner_version,
                 artifact.key,artifact.revision,artifact.size,route_id,verifier_id,
                 environment_digest,hashlib.sha256(credential).hexdigest(),issued_at,request.deadline))
            return VerifierAssignment(request, artifact, route_id, verifier_id,
                                      environment_digest, credential)

    def register(self, *, request_id: str, route_id: str, verifier_id: str,
                 environment_digest: str, artifact: Artifact, credential: bytes,
                 results) -> VerificationResult:
        if (not _matches(_ID, request_id) or not _matches(_ROUTE, route_id)
                or not _matches(_ID, verifier_id) or not _matches(_DIGEST, environment_digest)
                or type(artifact) is not Artifact or type(credential) is not bytes
                or len(credential) != 32):
            raise VerificationError('verifier_unauthorized')
        with self._ledger._transaction() as db:
            if db.execute('PRAGMA user_version').fetchone()[0] != 13:
                raise VerificationError('verifier_schema_required')
            dispatch = db.execute('SELECT * FROM verification_dispatches WHERE request_id=?',
                                  (request_id,)).fetchone()
            stored_digest = bytes.fromhex(dispatch['credential_digest']) if dispatch else _MISSING_DIGEST
            if not hmac.compare_digest(hashlib.sha256(credential).digest(), stored_digest):
                raise VerificationError('verifier_unauthorized')
            if (dispatch['route_id'] != route_id or dispatch['verifier_id'] != verifier_id
                    or dispatch['environment_digest'] != environment_digest
                    or (dispatch['artifact_key'],dispatch['snapshot_revision'],dispatch['artifact_size']) !=
                       (artifact.key,artifact.revision,artifact.size)):
                raise VerificationError('verifier_unauthorized')
            request_row = db.execute('SELECT * FROM verification_requests WHERE id=?',
                                     (request_id,)).fetchone()
            if request_row is None:
                raise VerificationError('verifier_unauthorized')
            request = self._ledger._decode(request_row)
            now = int(time.time())
            if (not dispatch['issued_at'] <= now <= dispatch['deadline']
                    or db.execute('SELECT 1 FROM verification_results WHERE request_id=?',
                                  (request_id,)).fetchone() is not None):
                raise VerificationError('verification_expired')
            if (request.project_id != dispatch['project_id']
                    or request.workspace_id != dispatch['workspace_id']
                    or request.revision_id != dispatch['revision_id']
                    or request.contract.digest != dispatch['contract_digest']
                    or request.policy_digest != dispatch['policy_digest']
                    or request.runner_version != dispatch['runner_version']
                    or _contract(db, request.project_id).digest != request.contract.digest):
                raise VerificationError('verification_stale_evidence')
            scope = db.execute('''SELECT w.current_revision_id,w.active_attempt_id,p.active_run_id,p.status,
                r.artifact_key,r.snapshot_revision,a.size FROM revision_workspaces w
                JOIN projects p ON p.id=w.project_id
                JOIN revision_records r ON r.id=? AND r.workspace_id=w.id
                JOIN revision_artifacts a ON a.key=r.artifact_key AND a.revision=r.snapshot_revision
                WHERE w.id=? AND w.project_id=?''',
                (request.revision_id,request.workspace_id,request.project_id)).fetchone()
            if (scope is None or scope['current_revision_id'] != request.revision_id
                    or scope['active_attempt_id'] is not None or scope['active_run_id'] is not None
                    or scope['status'] != 'ready'
                    or (scope['artifact_key'],scope['snapshot_revision'],scope['size']) !=
                       (artifact.key,artifact.revision,artifact.size)):
                raise VerificationError('verification_stale_evidence')
            try:
                report = capture_report(request.contract, results)
            except ContractError:
                raise VerificationError('invalid_verification_report') from None
            completed_at = int(time.time())
            if not dispatch['issued_at'] <= completed_at <= dispatch['deadline']:
                raise VerificationError('verification_expired')
            outcome = 'passed' if report.passed == report.total else 'failed'
            canonical = report.canonical.decode('utf-8')
            db.execute('''INSERT INTO verification_results
                (request_id,workspace_id,revision_id,contract_digest,policy_digest,outcome,
                 total,passed,report_json,completed_at) VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (request.id,request.workspace_id,request.revision_id,request.contract.digest,
                 request.policy_digest,outcome,report.total,report.passed,canonical,completed_at))
            db.execute('''INSERT INTO verification_attestations
                (request_id,verifier_id,environment_digest,artifact_key,snapshot_revision,
                 report_digest,observed_at) VALUES (?,?,?,?,?,?,?)''',
                (request.id,verifier_id,environment_digest,artifact.key,artifact.revision,
                 hashlib.sha256(report.canonical).hexdigest(),completed_at))
            return VerificationResult(request.id,request.revision_id,request.contract.digest,
                                      outcome,report.total,report.passed,report.canonical,completed_at)
