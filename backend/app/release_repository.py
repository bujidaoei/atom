"""Atomic release metadata for trusted orchestration; does not serve artifacts."""
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import io
import json
import re
import sqlite3
import time
from threading import BoundedSemaphore

from .verification_contract import capture_contract, load_report, ContractError
from .verification_repository import VerificationRepository, VerificationError
from .artifacts import Artifact, ArtifactError, ArtifactStore
from .content_policy import validate_content_manifest
from .snapshots import SnapshotError, verify_snapshot
from .content_bindings import ensure_binding
from .security_audit import record_release_transition


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
class RollbackReceipt:
    release_id: str
    source_release_id: str
    displaced_release_id: str
    generation: int
    slug: str


@dataclass(frozen=True)
class PublishedArtifact:
    project_id: str
    release_id: str
    revision_id: str
    artifact: Artifact


@dataclass(frozen=True)
class CurrentRelease:
    release_id: str
    revision_id: str
    verification_id: str | None
    contract_digest: str | None
    policy_digest: str | None
    audience: str
    slug: str
    generation: int
    live: bool
    binding_id: str
    verification_mode: str = 'required'


class ReleaseRepository:
    def __init__(self, path, *, lock_timeout=3, required_schema=None):
        if required_schema not in (None, 13, 14, 15, 16, 'verified'):
            raise VerificationError('invalid_release_configuration')
        self._required_schema = required_schema
        self._ledger = VerificationRepository(path, lock_timeout=lock_timeout)

    def _allows_schema(self, version: int) -> bool:
        return (self._required_schema is None
                or version == self._required_schema
                or (self._required_schema == 'verified' and version in (13, 14, 15, 16)))

    def current(self, *, owner: str, project_id: str) -> CurrentRelease | None:
        """Read the owner-scoped verified pointer without reserving the writer lock."""
        if any(type(value) is not str or re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', value) is None
               for value in (owner, project_id)):
            raise VerificationError('invalid_release_request')
        try:
            with closing(sqlite3.connect(self._ledger.path.as_uri() + '?mode=ro', uri=True,
                                         timeout=self._ledger.timeout)) as db:
                db.row_factory = sqlite3.Row
                db.execute('PRAGMA query_only=ON')
                db.execute('BEGIN')
                version = db.execute('PRAGMA user_version').fetchone()[0]
                if version not in (13, 14, 15, 16) or not self._allows_schema(version):
                    raise VerificationError('verified_release_schema_required')
                project = db.execute('SELECT 1 FROM projects WHERE id=? AND user_id=?',
                                     (project_id, owner)).fetchone()
                if project is None:
                    raise VerificationError('release_not_found')
                mode_sql = 'r.verification_mode' if version == 16 else "'required'"
                row = db.execute(f'''SELECT {mode_sql} AS verification_mode,p.release_id,p.slug,p.generation,p.live,
                    r.revision_id,r.verification_id,r.contract_digest,r.policy_digest,
                    r.audience,b.id AS binding_id FROM release_publications p
                    JOIN release_records r ON r.id=p.release_id AND r.project_id=p.project_id
                    LEFT JOIN content_bindings b ON b.project_id=r.project_id AND b.release_id=r.id
                    WHERE p.project_id=?''', (project_id,)).fetchone()
                if row is None:
                    return None
                if (row['binding_id'] is None or type(row['generation']) is not int
                        or row['generation'] < 1 or row['live'] not in (0, 1)):
                    raise VerificationError('release_corrupt')
                return CurrentRelease(row['release_id'], row['revision_id'],
                    row['verification_id'], row['contract_digest'], row['policy_digest'],
                    row['audience'], row['slug'], row['generation'], bool(row['live']),
                    row['binding_id'], row['verification_mode'])
        except sqlite3.Error:
            raise VerificationError('release_unavailable') from None

    def resolve(self, *, slug: str, viewer: str | None = None, release_id: str | None = None) -> PublishedArtifact:
        """Resolve authorized immutable metadata, never a mutable workspace.

        A pinned old release remains subject to current publication visibility
        and its own audience. Schema16 additionally permits authenticated owner
        previews after withdrawal. Consumers must verify stored artifact bytes.
        """
        if (not isinstance(slug,str) or len(slug)>63 or re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',slug) is None
            or any(value is not None and (not isinstance(value,str) or re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',value) is None)
                   for value in (viewer,release_id))):
            raise VerificationError('release_not_found')
        with self._ledger._transaction() as db:
            if not self._allows_schema(db.execute('PRAGMA user_version').fetchone()[0]):
                raise VerificationError('verified_release_schema_required')
            current = db.execute('''SELECT p.project_id,p.release_id,p.live,r.audience,o.user_id
                FROM release_publications p JOIN release_records r ON r.id=p.release_id AND r.project_id=p.project_id
                JOIN projects o ON o.id=p.project_id WHERE p.slug=?''',(slug,)).fetchone()
            retained_owner = (current is not None and viewer == current['user_id']
                              and db.execute('PRAGMA user_version').fetchone()[0] == 16)
            if (current is None or (not current['live'] and not retained_owner)
                    or (current['audience']!='public' and viewer!=current['user_id'])):
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
        """Strict publication preserves trusted passing-evidence requirements."""
        return self.publish_snapshot(store, verification_mode='required', **intent)

    def publish_snapshot(self, store: ArtifactStore, *, verification_mode='advisory', **intent) -> ReleaseReceipt:
        """Validate stored content before promotion, without holding the DB lock.

        This validates artifact integrity/policy, not independent verifier identity.
        Exact committed replay returns its receipt without reading storage again.
        """
        intent = {'verification_id': None, 'policy_digest': None, 'runner_version': None,
                  **intent, 'verification_mode': verification_mode}
        candidate = self._publish(**intent, _preflight=True)
        if isinstance(candidate, ReleaseReceipt):
            return candidate
        if not _PREFLIGHTS.acquire(timeout=3):
            raise VerificationError('release_capacity')
        try:
            payload = store.read(candidate.key)
            try:
                manifest = verify_snapshot(io.BytesIO(payload))
            except SnapshotError:
                raise ArtifactError('release_artifact_mismatch') from None
            if (hashlib.sha256(payload).hexdigest() != candidate.key
                    or len(payload) != candidate.size or manifest.revision != candidate.revision):
                raise ArtifactError('release_artifact_mismatch')
            validate_content_manifest(manifest)
            # Repeat all current authorization/evidence/generation checks and
            # compare the exact captured descriptor inside the promotion lock.
            return self._publish(**intent, _expected_artifact=candidate)
        finally:
            _PREFLIGHTS.release()

    def rollback_verified(self, store: ArtifactStore, **intent) -> RollbackReceipt:
        return self.restore_snapshot(store, verification_mode='required', **intent)

    def restore_snapshot(self, store: ArtifactStore, *, verification_mode='advisory', **intent) -> RollbackReceipt:
        """Create a new v14 release from trusted historical bytes and evidence.

        A receipt replay is read from the ledger without consulting mutable
        storage. Fresh admission verifies retained bytes outside the writer
        transaction, then repeats every ledger fence before promotion.
        """
        intent = {'policy_digest': None, 'runner_version': None, **intent,
                  'verification_mode': verification_mode}
        candidate = self._rollback(**intent, _preflight=True)
        if isinstance(candidate, RollbackReceipt):
            return candidate
        if not _PREFLIGHTS.acquire(timeout=3):
            raise VerificationError('release_capacity')
        try:
            payload = store.read(candidate.key)
            try:
                manifest = verify_snapshot(io.BytesIO(payload))
            except SnapshotError:
                raise ArtifactError('release_artifact_mismatch') from None
            if (hashlib.sha256(payload).hexdigest() != candidate.key
                    or len(payload) != candidate.size or manifest.revision != candidate.revision):
                raise ArtifactError('release_artifact_mismatch')
            validate_content_manifest(manifest)
            return self._rollback(**intent, _expected_artifact=candidate)
        finally:
            _PREFLIGHTS.release()

    def _rollback(self, *, owner, project_id, command_id, release_id,
                  source_release_id, expected_release, expected_generation,
                  expected_revision, policy_digest, runner_version,
                  verification_mode='required', _preflight=False, _expected_artifact=None) -> RollbackReceipt | Artifact:
        if verification_mode not in ('advisory', 'required'):
            raise VerificationError('invalid_release_request')
        if verification_mode == 'advisory' and (policy_digest is not None or runner_version is not None):
            raise VerificationError('invalid_release_request')
        identifiers = (owner, project_id, source_release_id, expected_release,
                       expected_revision)
        if verification_mode == 'required':
            identifiers += (runner_version,)
        if (any(type(value) is not str or re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', value) is None
                for value in identifiers)
                or any(type(value) is not str or re.fullmatch(r'[0-9a-f]{32}', value) is None
                       for value in (command_id, release_id))
                or type(expected_generation) is not int
                or not 1 <= expected_generation < 2**63-1
                or (verification_mode == 'required' and (type(policy_digest) is not str
                    or re.fullmatch(r'[0-9a-f]{64}', policy_digest) is None))):
            raise VerificationError('invalid_release_request')
        intent = dict(owner=owner, project_id=project_id, command_id=command_id,
                      release_id=release_id, source_release_id=source_release_id,
                      expected_release=expected_release,
                      expected_generation=expected_generation,
                      expected_revision=expected_revision,
                      policy_digest=policy_digest, runner_version=runner_version)
        if verification_mode == 'advisory':
            intent['verification_mode'] = verification_mode
        digest = hashlib.sha256(json.dumps(intent, sort_keys=True,
                                            separators=(',', ':')).encode()).hexdigest()
        with self._ledger._transaction() as db:
            schema_version = db.execute('PRAGMA user_version').fetchone()[0]
            if schema_version not in (14, 15, 16):
                raise VerificationError('verified_rollback_schema_required')
            if verification_mode == 'advisory' and schema_version != 16:
                raise VerificationError('publication_policy_schema_required')
            if not self._allows_schema(schema_version):
                raise VerificationError('verified_rollback_schema_required')
            project = db.execute('SELECT * FROM projects WHERE id=? AND user_id=?',
                                 (project_id, owner)).fetchone()
            if project is None:
                raise VerificationError('release_not_found')
            key = 'rollback:' + command_id
            prior = db.execute('SELECT digest,response_json FROM command_receipts '
                               'WHERE project_id=? AND key=?', (project_id, key)).fetchone()
            if prior is not None:
                if prior['digest'] != digest:
                    raise VerificationError('release_conflict')
                try:
                    response = RollbackReceipt(**json.loads(prior['response_json']))
                except (TypeError, ValueError):
                    raise VerificationError('release_corrupt') from None
                if (type(response.slug) is not str
                        or re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', response.slug) is None
                        or len(response.slug) > 63):
                    raise VerificationError('release_corrupt')
                relation = db.execute('SELECT * FROM release_rollback_sources '
                                      'WHERE new_release_id=? AND project_id=?',
                                      (release_id, project_id)).fetchone()
                persisted = db.execute('SELECT 1 FROM release_records r '
                    'JOIN content_bindings b ON b.release_id=r.id AND b.project_id=r.project_id '
                    'JOIN release_publications p ON p.project_id=r.project_id '
                    'WHERE r.id=? AND r.project_id=? AND p.slug=?',
                    (release_id, project_id, response.slug)).fetchone()
                if (relation is None or response != RollbackReceipt(
                        release_id, source_release_id, expected_release,
                        expected_generation + 1, response.slug)
                        or persisted is None
                        or (relation['source_release_id'], relation['displaced_release_id'],
                            relation['command_id'], relation['generation']) != (
                            source_release_id, expected_release, command_id,
                            response.generation)):
                    raise VerificationError('release_corrupt')
                return response
            pointer = db.execute('SELECT * FROM release_publications WHERE project_id=?',
                                 (project_id,)).fetchone()
            if (pointer is None or pointer['release_id'] != expected_release
                    or pointer['generation'] != expected_generation
                    or (schema_version != 16 and pointer['live'] != 1)):
                raise VerificationError('release_conflict')
            workspace = db.execute('SELECT * FROM revision_workspaces '
                                   'WHERE project_id=? AND heat_id IS NULL',
                                   (project_id,)).fetchone()
            if (workspace is None or workspace['current_revision_id'] != expected_revision
                    or workspace['active_attempt_id'] is not None
                    or project['active_run_id'] is not None
                    or (verification_mode == 'required' and project['status'] != 'ready')):
                raise VerificationError('release_conflict')
            source = db.execute('SELECT * FROM release_records WHERE id=? AND project_id=?',
                                (source_release_id, project_id)).fetchone()
            displaced = db.execute('SELECT * FROM release_records WHERE id=? AND project_id=?',
                                   (expected_release, project_id)).fetchone()
            if (source is None or displaced is None
                    or (schema_version != 16 and source_release_id == expected_release)
                    or release_id in (source_release_id, expected_release)
                    or source['workspace_id'] != workspace['id']
                    or (schema_version != 16 and source['audience'] != displaced['audience'])
                    or (verification_mode == 'required' and source['policy_digest'] != policy_digest)):
                raise VerificationError('release_conflict')
            descriptor = db.execute('''SELECT a.key,a.revision,a.size FROM revision_records v
                JOIN revision_artifacts a ON a.key=v.artifact_key AND a.revision=v.snapshot_revision
                WHERE v.id=? AND v.workspace_id=? AND v.project_id=?''',
                (source['revision_id'], workspace['id'], project_id)).fetchone()
            if descriptor is None:
                raise VerificationError('release_artifact_required')
            if verification_mode == 'required':
                rows = db.execute('SELECT key,title,detail,checks_json FROM requirements '
                                  'WHERE project_id=? ORDER BY position,id LIMIT 129',
                                  (project_id,)).fetchall()
                try:
                    contract = capture_contract([{'key': row['key'], 'title': row['title'],
                        'detail': row['detail'], 'checks': json.loads(row['checks_json'])}
                        for row in rows])
                except (ContractError, ValueError, TypeError, RecursionError):
                    raise VerificationError('invalid_stored_contract') from None
                if contract.digest != source['contract_digest']:
                    raise VerificationError('release_stale_evidence')
                evidence = db.execute('''SELECT r.*,q.runner_version FROM verification_results r
                    JOIN verification_requests q ON q.id=r.request_id
                    WHERE r.request_id=? AND r.workspace_id=? AND r.revision_id=?''',
                    (source['verification_id'], workspace['id'], source['revision_id'])).fetchone()
                attestation = db.execute('''SELECT d.artifact_key,d.snapshot_revision,d.artifact_size,
                    d.contract_digest,d.policy_digest,d.runner_version,t.report_digest,t.observed_at
                    FROM verification_dispatches d JOIN verification_attestations t
                      ON t.request_id=d.request_id AND t.verifier_id=d.verifier_id
                     AND t.environment_digest=d.environment_digest
                     AND t.artifact_key=d.artifact_key AND t.snapshot_revision=d.snapshot_revision
                    WHERE d.request_id=? AND d.project_id=? AND d.workspace_id=? AND d.revision_id=?''',
                    (source['verification_id'], project_id, workspace['id'],
                     source['revision_id'])).fetchone()
                if (evidence is None or descriptor is None or attestation is None
                        or evidence['outcome'] != 'passed'
                        or evidence['contract_digest'] != contract.digest
                        or evidence['policy_digest'] != policy_digest
                        or evidence['runner_version'] != runner_version
                        or (attestation['contract_digest'], attestation['policy_digest'],
                            attestation['runner_version']) != (
                            contract.digest, policy_digest, runner_version)
                        or (descriptor['key'], descriptor['revision'], descriptor['size']) != (
                            attestation['artifact_key'], attestation['snapshot_revision'],
                            attestation['artifact_size'])
                        or evidence['completed_at'] != attestation['observed_at']):
                    raise VerificationError('release_untrusted_evidence')
                try:
                    canonical = evidence['report_json'].encode('utf-8')
                    report = load_report(contract, canonical)
                except (ContractError, UnicodeError):
                    raise VerificationError('release_corrupt_evidence') from None
                if (report.total != evidence['total'] or report.passed != evidence['passed']
                        or not hmac.compare_digest(hashlib.sha256(canonical).hexdigest(),
                                                   attestation['report_digest'])):
                    raise VerificationError('release_untrusted_evidence')
            artifact = Artifact(descriptor['key'], descriptor['revision'], descriptor['size'])
            if _preflight:
                return artifact
            if artifact != _expected_artifact:
                raise VerificationError('release_conflict')
            generation = expected_generation + 1
            created_at = int(time.time())
            columns = 'id,project_id,workspace_id,revision_id,verification_id,contract_digest,policy_digest,audience,creator_id,previous_release_id,created_at'
            required = verification_mode == 'required'
            values = [release_id,project_id,workspace['id'],source['revision_id'],
                      source['verification_id'] if required else None,
                      source['contract_digest'] if required else None,
                      policy_digest,source['audience'],owner,expected_release,created_at]
            if schema_version == 16:
                columns += ',verification_mode,publication_generation'
                values.extend((verification_mode, expected_generation + 1))
            db.execute(f"INSERT INTO release_records ({columns}) VALUES ({','.join('?' for _ in values)})", values)
            ensure_binding(db, project_id=project_id, release_id=release_id)
            db.execute('UPDATE release_publications SET release_id=?,generation=?,live=1 '
                       'WHERE project_id=?', (release_id, generation, project_id))
            receipt = RollbackReceipt(release_id, source_release_id, expected_release,
                                      generation, pointer['slug'])
            db.execute('INSERT INTO command_receipts VALUES (?,?,?,?,?)',
                       (project_id, key, digest,
                        json.dumps(receipt.__dict__, sort_keys=True, separators=(',', ':')),
                        datetime.now(timezone.utc).isoformat()))
            record_release_transition(db, kind='release.published', user_id=owner,
                                      project_id=project_id, release_id=release_id,
                                      operation_id=release_id, generation=generation,
                                      occurred_at=created_at)
            db.execute('INSERT INTO release_rollback_sources VALUES (?,?,?,?,?,?,?)',
                       (release_id, project_id, source_release_id, expected_release,
                        command_id, generation, created_at))
            return receipt

    def _publish(self, *, owner, project_id, release_id, verification_id, expected_revision,
                 expected_generation, policy_digest, runner_version, audience, slug,
                 verification_mode='required', _preflight=False, _expected_artifact=None) -> ReleaseReceipt | Artifact:
        """Requires a trusted coordinator to authenticate verifier provenance.

        The persisted report alone is not evidence of browser execution. This
        operation is deliberately not exposed by the legacy publication API.
        """
        if verification_mode not in ('advisory', 'required'):
            raise VerificationError('invalid_release_request')
        evidence_values = (verification_id, runner_version) if verification_mode == 'required' else ()
        if verification_mode == 'advisory' and any(value is not None for value in
                                                   (verification_id, runner_version, policy_digest)):
            raise VerificationError('invalid_release_request')
        for value in (owner,project_id,release_id,expected_revision, *evidence_values):
            if not isinstance(value,str) or re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',value) is None:
                raise VerificationError('invalid_release_request')
        if (type(expected_generation) is not int or not 0 <= expected_generation < 2**63-1
            or audience not in ('owner','public') or not isinstance(slug,str)
            or re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',slug) is None or len(slug)>63
            or (verification_mode == 'required' and (not isinstance(policy_digest,str)
                or re.fullmatch(r'[0-9a-f]{64}',policy_digest) is None))):
            raise VerificationError('invalid_release_request')
        intent = dict(owner=owner,project_id=project_id,release_id=release_id,verification_id=verification_id,
            expected_revision=expected_revision,expected_generation=expected_generation,policy_digest=policy_digest,
            runner_version=runner_version,audience=audience,slug=slug)
        # Preserve historical strict receipt digests; advisory identity includes its policy.
        if verification_mode == 'advisory':
            intent['verification_mode'] = verification_mode
        digest = hashlib.sha256(json.dumps(intent,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        key = 'release:' + release_id
        with self._ledger._transaction() as db:
            schema_version = db.execute('PRAGMA user_version').fetchone()[0]
            if not self._allows_schema(schema_version):
                raise VerificationError('verified_release_schema_required')
            if verification_mode == 'advisory' and schema_version != 16:
                raise VerificationError('publication_policy_schema_required')
            if schema_version in (13, 14, 15, 16) and not (_preflight or _expected_artifact is not None):
                raise VerificationError('verified_release_required')
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
                or workspace['active_attempt_id'] is not None or project['active_run_id'] is not None
                or (schema_version in (13, 14, 15, 16) and project['status'] != 'ready')):
                raise VerificationError('release_conflict')
            pointer = db.execute('SELECT * FROM release_publications WHERE project_id=?',(project_id,)).fetchone()
            if (pointer['generation'] if pointer else 0) != expected_generation or (pointer and pointer['slug'] != slug):
                raise VerificationError('release_conflict')
            contract_digest = None
            if verification_mode == 'required':
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
                if schema_version in (13, 14, 15, 16):
                    attestation = db.execute('''SELECT d.project_id,d.workspace_id,d.revision_id,
                        d.contract_digest,d.policy_digest,d.runner_version,d.artifact_key,
                        d.snapshot_revision,d.artifact_size,t.verifier_id,t.environment_digest,
                        t.report_digest,t.observed_at
                        FROM verification_dispatches d JOIN verification_attestations t
                          ON t.request_id=d.request_id AND t.verifier_id=d.verifier_id
                         AND t.environment_digest=d.environment_digest
                         AND t.artifact_key=d.artifact_key AND t.snapshot_revision=d.snapshot_revision
                        WHERE d.request_id=?''',(verification_id,)).fetchone()
                    try:
                        canonical = evidence['report_json'].encode('utf-8')
                        report = load_report(contract,canonical)
                    except (ContractError, UnicodeError):
                        raise VerificationError('release_corrupt_evidence') from None
                    if (attestation is None or (attestation['project_id'],attestation['workspace_id'],
                        attestation['revision_id'],attestation['contract_digest'],attestation['policy_digest'],
                        attestation['runner_version']) != (project_id,workspace['id'],expected_revision,
                        contract.digest,policy_digest,runner_version)
                        or evidence['completed_at'] != attestation['observed_at']
                        or report.total != evidence['total'] or report.passed != evidence['passed']
                        or not hmac.compare_digest(hashlib.sha256(canonical).hexdigest(),
                                                   attestation['report_digest'])):
                        raise VerificationError('release_untrusted_evidence')
                contract_digest = contract.digest
            if _preflight or _expected_artifact is not None:
                row = db.execute('''SELECT a.key,a.revision,a.size FROM revision_records r
                    JOIN revision_artifacts a ON a.key=r.artifact_key AND a.revision=r.snapshot_revision
                    WHERE r.id=? AND r.workspace_id=? AND r.project_id=?''',
                    (expected_revision,workspace['id'],project_id)).fetchone()
                if row is None:
                    raise VerificationError('release_artifact_required')
                artifact = Artifact(row['key'],row['revision'],row['size'])
                if verification_mode == 'required' and schema_version in (13, 14, 15, 16) and (artifact.key,artifact.revision,artifact.size) != (
                        attestation['artifact_key'],attestation['snapshot_revision'],attestation['artifact_size']):
                    raise VerificationError('release_untrusted_evidence')
                if _preflight:
                    return artifact
                if artifact != _expected_artifact:
                    raise VerificationError('release_conflict')
            columns = 'id,project_id,workspace_id,revision_id,verification_id,contract_digest,policy_digest,audience,creator_id,previous_release_id,created_at'
            values = [release_id,project_id,workspace['id'],expected_revision,verification_id,
                      contract_digest,policy_digest,audience,owner,
                      pointer['release_id'] if pointer else None,int(time.time())]
            if schema_version == 16:
                columns += ',verification_mode,publication_generation'
                values.extend((verification_mode, expected_generation + 1))
            db.execute(f"INSERT INTO release_records ({columns}) VALUES ({','.join('?' for _ in values)})", values)
            if schema_version in (3, 4, 5, 6, 7, 9, 10, 12, 13, 14, 15, 16):
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
            if schema_version in (5,6,7,9,10,12,13,14,15,16):
                record_release_transition(db,kind='release.published',user_id=owner,project_id=project_id,
                    release_id=release_id,operation_id=release_id,generation=generation,occurred_at=int(time.time()))
            return receipt

    def unpublish(self, *, owner, project_id, command_id, expected_release, expected_generation,
                  require_verified_schema=False) -> UnpublishReceipt:
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
            schema_version = db.execute('PRAGMA user_version').fetchone()[0]
            if ((require_verified_schema and schema_version not in (13, 14, 15, 16))
                    or not self._allows_schema(schema_version)):
                raise VerificationError('release_schema_required')
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
            if db.execute('PRAGMA user_version').fetchone()[0] in (5,6,7,9,10,12,13,14,15,16):
                record_release_transition(db,kind='release.unpublished',user_id=owner,project_id=project_id,
                    release_id=expected_release,operation_id=command_id,generation=receipt.generation,occurred_at=int(time.time()))
            return receipt
