"""Atomic release metadata for trusted orchestration; does not serve artifacts."""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import io
import json
import re
import time
from threading import BoundedSemaphore

from .verification_contract import capture_contract, ContractError
from .verification_repository import VerificationRepository, VerificationError
from .artifacts import Artifact, ArtifactError, ArtifactStore
from .content_policy import validate_content_manifest
from .snapshots import verify_snapshot
from .content_bindings import ensure_binding


_PREFLIGHTS = BoundedSemaphore(1)


@dataclass(frozen=True)
class ReleaseReceipt:
    release_id: str
    revision_id: str
    generation: int
    slug: str


@dataclass(frozen=True)
class UnpublishReceipt:
    command_id: str
    release_id: str
    generation: int


@dataclass(frozen=True)
class PublishedArtifact:
    project_id: str
    release_id: str
    revision_id: str
    artifact: Artifact


class ReleaseRepository:
    def __init__(self, path, *, lock_timeout=3):
        self._ledger = VerificationRepository(path, lock_timeout=lock_timeout)

    def resolve(self, *, slug: str, viewer: str | None = None, release_id: str | None = None) -> PublishedArtifact:
        """Resolve authorized immutable metadata, never a mutable workspace.

        A pinned old release remains subject to current publication visibility
        and its own audience. Consumers must verify stored artifact bytes.
        """
        if (not isinstance(slug,str) or len(slug)>63 or re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',slug) is None
            or any(value is not None and (not isinstance(value,str) or re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',value) is None)
                   for value in (viewer,release_id))):
            raise VerificationError('release_not_found')
        with self._ledger._transaction() as db:
            current = db.execute('''SELECT p.project_id,p.release_id,p.live,r.audience,o.user_id
                FROM release_publications p JOIN release_records r ON r.id=p.release_id AND r.project_id=p.project_id
                JOIN projects o ON o.id=p.project_id WHERE p.slug=?''',(slug,)).fetchone()
            if current is None or not current['live'] or (current['audience']!='public' and viewer!=current['user_id']):
                raise VerificationError('release_not_found')
            row = db.execute('''SELECT r.id,r.revision_id,r.audience,a.key,a.revision,a.size
                FROM release_records r JOIN revision_records v ON v.id=r.revision_id AND v.workspace_id=r.workspace_id
                JOIN revision_artifacts a ON a.key=v.artifact_key AND a.revision=v.snapshot_revision
                WHERE r.id=? AND r.project_id=?''',(release_id or current['release_id'],current['project_id'])).fetchone()
            if row is None or (row['audience']!='public' and viewer!=current['user_id']):
                raise VerificationError('release_not_found')
            return PublishedArtifact(current['project_id'],row['id'],row['revision_id'],
                                     Artifact(row['key'],row['revision'],row['size']))

    def publish(self, **intent) -> ReleaseReceipt:
        """Internal metadata operation; callers need trusted verifier provenance.

        Application coordinators must use publish_verified for content releases.
        This method remains available for metadata fixtures and ledger operations.
        """
        return self._publish(**intent)

    def publish_verified(self, store: ArtifactStore, **intent) -> ReleaseReceipt:
        """Validate stored content before promotion, without holding the DB lock.

        This validates artifact integrity/policy, not independent verifier identity.
        Exact committed replay returns its receipt without reading storage again.
        """
        candidate = self._publish(**intent, _preflight=True)
        if isinstance(candidate, ReleaseReceipt):
            return candidate
        if not _PREFLIGHTS.acquire(timeout=3):
            raise VerificationError('release_capacity')
        try:
            payload = store.read(candidate.key)
            manifest = verify_snapshot(io.BytesIO(payload))
            if (hashlib.sha256(payload).hexdigest() != candidate.key
                    or len(payload) != candidate.size or manifest.revision != candidate.revision):
                raise ArtifactError('release_artifact_mismatch')
            validate_content_manifest(manifest)
            # Repeat all current authorization/evidence/generation checks and
            # compare the exact captured descriptor inside the promotion lock.
            return self._publish(**intent, _expected_artifact=candidate)
        finally:
            _PREFLIGHTS.release()

    def _publish(self, *, owner, project_id, release_id, verification_id, expected_revision,
                 expected_generation, policy_digest, runner_version, audience, slug,
                 _preflight=False, _expected_artifact=None) -> ReleaseReceipt | Artifact:
        """Requires a trusted coordinator to authenticate verifier provenance.

        The persisted report alone is not evidence of browser execution. This
        operation is deliberately not exposed by the legacy publication API.
        """
        for value in (owner,project_id,release_id,verification_id,expected_revision,runner_version):
            if not isinstance(value,str) or re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',value) is None:
                raise VerificationError('invalid_release_request')
        if (type(expected_generation) is not int or not 0 <= expected_generation < 2**63-1
            or audience not in ('owner','public') or not isinstance(slug,str)
            or re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',slug) is None or len(slug)>63
            or not isinstance(policy_digest,str) or re.fullmatch(r'[0-9a-f]{64}',policy_digest) is None):
            raise VerificationError('invalid_release_request')
        intent = dict(owner=owner,project_id=project_id,release_id=release_id,verification_id=verification_id,
            expected_revision=expected_revision,expected_generation=expected_generation,policy_digest=policy_digest,
            runner_version=runner_version,audience=audience,slug=slug)
        digest = hashlib.sha256(json.dumps(intent,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        key = 'release:' + release_id
        with self._ledger._transaction() as db:
            project = db.execute('SELECT * FROM projects WHERE id=? AND user_id=?',(project_id,owner)).fetchone()
            if project is None:
                raise VerificationError('release_not_found')
            prior = db.execute('SELECT digest,response_json FROM command_receipts WHERE project_id=? AND key=?',(project_id,key)).fetchone()
            if prior is not None:
                if prior['digest'] != digest:
                    raise VerificationError('release_conflict')
                record = db.execute('SELECT * FROM release_records WHERE id=? AND project_id=?',(release_id,project_id)).fetchone()
                try:
                    receipt = ReleaseReceipt(**json.loads(prior['response_json']))
                except (TypeError,ValueError):
                    raise VerificationError('release_corrupt') from None
                if record is None or receipt != ReleaseReceipt(release_id,expected_revision,expected_generation+1,slug):
                    raise VerificationError('release_corrupt')
                return receipt
            workspace = db.execute('SELECT * FROM revision_workspaces WHERE project_id=? AND heat_id IS NULL',(project_id,)).fetchone()
            if (workspace is None or workspace['current_revision_id'] != expected_revision
                or workspace['active_attempt_id'] is not None or project['active_run_id'] is not None):
                raise VerificationError('release_conflict')
            pointer = db.execute('SELECT * FROM release_publications WHERE project_id=?',(project_id,)).fetchone()
            if (pointer['generation'] if pointer else 0) != expected_generation or (pointer and pointer['slug'] != slug):
                raise VerificationError('release_conflict')
            evidence = db.execute('''SELECT r.*,v.runner_version FROM verification_results r
                JOIN verification_requests v ON v.id=r.request_id
                WHERE r.request_id=? AND r.workspace_id=? AND r.revision_id=?''',
                (verification_id,workspace['id'],expected_revision)).fetchone()
            if (evidence is None or evidence['outcome']!='passed' or evidence['policy_digest']!=policy_digest
                or evidence['runner_version']!=runner_version):
                raise VerificationError('release_evidence_required')
            requirements = db.execute('SELECT key,title,detail,checks_json FROM requirements WHERE project_id=? ORDER BY position,id LIMIT 129',(project_id,)).fetchall()
            try:
                contract = capture_contract([{'key':r['key'],'title':r['title'],'detail':r['detail'],
                    'checks':json.loads(r['checks_json'])} for r in requirements])
            except (ContractError,ValueError,TypeError,RecursionError):
                raise VerificationError('invalid_stored_contract') from None
            if contract.digest != evidence['contract_digest']:
                raise VerificationError('release_stale_evidence')
            if _preflight or _expected_artifact is not None:
                row = db.execute('''SELECT a.key,a.revision,a.size FROM revision_records r
                    JOIN revision_artifacts a ON a.key=r.artifact_key AND a.revision=r.snapshot_revision
                    WHERE r.id=? AND r.workspace_id=? AND r.project_id=?''',
                    (expected_revision,workspace['id'],project_id)).fetchone()
                if row is None:
                    raise VerificationError('release_artifact_required')
                artifact = Artifact(row['key'],row['revision'],row['size'])
                if _preflight:
                    return artifact
                if artifact != _expected_artifact:
                    raise VerificationError('release_conflict')
            db.execute('''INSERT INTO release_records
                (id,project_id,workspace_id,revision_id,verification_id,contract_digest,policy_digest,audience,creator_id,previous_release_id,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)''',(release_id,project_id,workspace['id'],expected_revision,verification_id,
                contract.digest,policy_digest,audience,owner,pointer['release_id'] if pointer else None,int(time.time())))
            if db.execute('PRAGMA user_version').fetchone()[0] in (3, 4):
                # The verified v3 schema supports serving identity. Allocate it
                # before promotion so binding, release, pointer and receipt are
                # committed together or all rolled back on any failure.
                ensure_binding(db,project_id=project_id,release_id=release_id)
            generation = expected_generation+1
            db.execute('''INSERT INTO release_publications(project_id,slug,release_id,generation,live) VALUES (?,?,?,?,1)
                ON CONFLICT(project_id) DO UPDATE SET release_id=excluded.release_id,generation=excluded.generation,live=1''',
                (project_id,slug,release_id,generation))
            receipt = ReleaseReceipt(release_id,expected_revision,generation,slug)
            db.execute('INSERT INTO command_receipts(project_id,key,digest,response_json,created_at) VALUES (?,?,?,?,?)',
                (project_id,key,digest,json.dumps(receipt.__dict__,sort_keys=True,separators=(',',':')),datetime.now(timezone.utc).isoformat()))
            return receipt

    def unpublish(self, *, owner, project_id, command_id, expected_release, expected_generation) -> UnpublishReceipt:
        for value in (owner,project_id,command_id,expected_release):
            if not isinstance(value,str) or re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',value) is None:
                raise VerificationError('invalid_release_request')
        if type(expected_generation) is not int or not 1 <= expected_generation < 2**63-1:
            raise VerificationError('invalid_release_request')
        intent = dict(owner=owner,project_id=project_id,command_id=command_id,
                      expected_release=expected_release,expected_generation=expected_generation)
        digest = hashlib.sha256(json.dumps(intent,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        key = 'unpublish:' + command_id
        with self._ledger._transaction() as db:
            if db.execute('SELECT 1 FROM projects WHERE id=? AND user_id=?',(project_id,owner)).fetchone() is None:
                raise VerificationError('release_not_found')
            prior = db.execute('SELECT digest,response_json FROM command_receipts WHERE project_id=? AND key=?',(project_id,key)).fetchone()
            receipt = UnpublishReceipt(command_id,expected_release,expected_generation+1)
            if prior is not None:
                if prior['digest'] != digest:
                    raise VerificationError('release_conflict')
                try:
                    recorded = UnpublishReceipt(**json.loads(prior['response_json']))
                except (TypeError,ValueError):
                    raise VerificationError('release_corrupt') from None
                if recorded != receipt:
                    raise VerificationError('release_corrupt')
                return recorded
            pointer = db.execute('SELECT * FROM release_publications WHERE project_id=?',(project_id,)).fetchone()
            if (pointer is None or pointer['release_id'] != expected_release
                or pointer['generation'] != expected_generation or not pointer['live']):
                raise VerificationError('release_conflict')
            db.execute('UPDATE release_publications SET live=0,generation=? WHERE project_id=?',
                       (receipt.generation,project_id))
            db.execute('INSERT INTO command_receipts(project_id,key,digest,response_json,created_at) VALUES (?,?,?,?,?)',
                (project_id,key,digest,json.dumps(receipt.__dict__,sort_keys=True,separators=(',',':')),datetime.now(timezone.utc).isoformat()))
            return receipt
