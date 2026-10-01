"""Trusted control-plane revision ledger; no runtime endpoints or worker IO.

Artifact metadata must come from completed immutable storage, and termination
observations from the broker coordinator. Neither is established by this ledger.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
import uuid

from .artifacts import Artifact
from .migrations import MigrationError, _schema, verify
from .snapshots import MAX_ARCHIVE_BYTES

_ID = re.compile(r'[A-Za-z0-9_-]{1,128}\Z')
_GRANT_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z')
_HASH = re.compile(r'[0-9a-f]{64}\Z')


class RevisionError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Attempt:
    id: str
    workspace_id: str
    run_id: str
    generation: int
    base_revision_id: str
    deadline: int
    broker_attempt_id: str | None
    grant_id: str
    issued_at: int
    project_id: str
    base_artifact_key: str
    base_revision: str


@dataclass(frozen=True)
class Receipt:
    attempt_id: str
    workspace_id: str
    revision_id: str
    artifact_key: str
    snapshot_revision: str


@dataclass(frozen=True)
class WorkspaceRevision:
    workspace_id: str
    revision_id: str
    artifact: Artifact
    created_at: int


@dataclass(frozen=True)
class PendingExecution:
    owner: str
    attempt_id: str


@dataclass(frozen=True)
class Recovery:
    """Cleanup observations only; deliberately excludes grant issuance inputs."""
    attempt_id: str
    workspace_id: str
    grant_id: str
    broker_attempt_id: str | None
    deadline: int
    state: str
    termination_state: str
    outcome: str | None
    receipt: Receipt | None


def _identifiers(*values):
    if any(not isinstance(value, str) or not _ID.fullmatch(value) for value in values):
        raise RevisionError('invalid_revision_request')


def _artifact(value):
    if (not isinstance(value, Artifact) or not isinstance(value.key, str)
            or not _HASH.fullmatch(value.key) or not isinstance(value.revision, str)
            or not _HASH.fullmatch(value.revision) or type(value.size) is not int
            or not 14 <= value.size <= MAX_ARCHIVE_BYTES):
        raise RevisionError('invalid_revision_request')


class RevisionRepository:
    def __init__(self, path: Path, *, lock_timeout: float = 3):
        if isinstance(lock_timeout, bool) or not isinstance(lock_timeout, (int, float)) or not 0 < lock_timeout <= 10:
            raise RevisionError('invalid_revision_configuration')
        self.path, self.timeout = Path(path), lock_timeout
        try:
            if verify(self.path) not in (1, 4, 5, 6, 7, 9, 10):
                raise RevisionError('revision_schema_required')
        except MigrationError:
            raise RevisionError('revision_schema_required') from None

    @contextmanager
    def _transaction(self):
        db = None
        try:
            db = sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True,
                                 timeout=self.timeout, isolation_level=None)
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            # Schema verifier compares tuple rows, so keep its connection view exact.
            db.row_factory = None
            version = _schema(db)
            db.row_factory = sqlite3.Row
            if version not in (1, 4, 5, 6, 7, 9, 10):
                raise RevisionError('revision_schema_required')
            yield db
            db.execute('COMMIT')
        except sqlite3.IntegrityError:
            raise RevisionError('revision_conflict') from None
        except (sqlite3.Error, OSError, MigrationError):
            raise RevisionError('revision_unavailable') from None
        finally:
            if db is not None:
                try:
                    if db.in_transaction:
                        db.rollback()
                finally:
                    db.close()

    @staticmethod
    def _workspace(db, owner, workspace):
        row = db.execute('''SELECT w.*,p.active_run_id,h.run_id AS heat_run_id
            FROM revision_workspaces w JOIN projects p ON p.id=w.project_id
            LEFT JOIN race_heats h ON h.id=w.heat_id WHERE w.id=? AND p.user_id=?''',
                         (workspace, owner)).fetchone()
        if row is None:
            raise RevisionError('revision_not_found')
        return row

    def _attempt(self, db, owner, attempt_id):
        row = db.execute('SELECT * FROM revision_attempts WHERE id=?', (attempt_id,)).fetchone()
        if row is None:
            raise RevisionError('revision_not_found')
        return row, self._workspace(db, owner, row['workspace_id'])

    @staticmethod
    def _current_run(db, workspace, run_id):
        current = workspace['active_run_id'] if workspace['heat_id'] is None else workspace['heat_run_id']
        run = db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
        if (current != run_id or run is None or run['status'] != 'running'
                or run['project_id'] != workspace['project_id'] or run['heat_id'] != workspace['heat_id']):
            raise RevisionError('revision_conflict')

    def _active(self, db, attempt, workspace, *, registered_head=None):
        if (attempt['state'] != 'active' or attempt['termination_state'] != 'pending' or attempt['outcome'] is not None
                or attempt['deadline'] <= int(time.time())
                or workspace['active_attempt_id'] != attempt['id']
                or workspace['generation'] != attempt['generation']
                or workspace['current_revision_id'] != (registered_head or attempt['base_revision_id'])):
            raise RevisionError('revision_conflict')
        self._current_run(db, workspace, attempt['run_id'])

    @staticmethod
    def _store_metadata(db, artifact):
        existing = db.execute('SELECT revision,size FROM revision_artifacts WHERE key=?', (artifact.key,)).fetchone()
        if existing is not None:
            if tuple(existing) != (artifact.revision, artifact.size):
                raise RevisionError('revision_conflict')
        else:
            db.execute('INSERT INTO revision_artifacts VALUES (?,?,?,?)',
                       (artifact.key, artifact.revision, artifact.size, int(time.time())))

    def find_workspace(self, owner: str, project_id: str, heat_id: str | None = None) -> str:
        _identifiers(owner, project_id)
        if heat_id is not None:
            _identifiers(heat_id)
        with self._transaction() as db:
            row = db.execute('''SELECT w.id FROM revision_workspaces w
                JOIN projects p ON p.id=w.project_id
                WHERE p.user_id=? AND w.project_id=? AND w.heat_id IS ?''',
                             (owner, project_id, heat_id)).fetchone()
            if row is None:
                raise RevisionError('revision_not_found')
            return row['id']

    def current_revision(self, owner: str, workspace_id: str) -> WorkspaceRevision | None:
        _identifiers(owner, workspace_id)
        with self._transaction() as db:
            workspace = self._workspace(db, owner, workspace_id)
            if workspace['current_revision_id'] is None:
                return None
            row = db.execute('''SELECT r.id,r.artifact_key,r.snapshot_revision,r.created_at,a.size
                FROM revision_records r JOIN revision_artifacts a ON a.key=r.artifact_key
                WHERE r.id=? AND r.workspace_id=?''',
                             (workspace['current_revision_id'], workspace_id)).fetchone()
            if row is None:
                raise RevisionError('revision_conflict')
            return WorkspaceRevision(workspace_id, row['id'],
                                     Artifact(row['artifact_key'], row['snapshot_revision'], row['size']), row['created_at'])

    def pending_executions(self, *, limit: int = 100) -> tuple[PendingExecution, ...]:
        """Trusted startup inventory, never a tenant-facing query or dispatch grant."""
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise RevisionError('invalid_revision_request')
        with self._transaction() as db:
            rows = db.execute('''SELECT p.user_id,a.id FROM revision_attempts a
                JOIN projects p ON p.id=a.project_id WHERE a.state!='closed'
                ORDER BY a.created_at,a.id LIMIT ?''', (limit + 1,)).fetchall()
            if len(rows) > limit:
                raise RevisionError('revision_recovery_capacity')
            return tuple(PendingExecution(row['user_id'], row['id']) for row in rows)

    def ensure_workspace(self, owner: str, project_id: str, heat_id: str | None = None) -> str:
        """Resolve a committed project scope without inventing an initial revision."""
        _identifiers(owner, project_id)
        if heat_id is not None:
            _identifiers(heat_id)
        with self._transaction() as db:
            project = db.execute('SELECT id FROM projects WHERE id=? AND user_id=?',
                                 (project_id, owner)).fetchone()
            if project is None:
                raise RevisionError('revision_not_found')
            if heat_id is not None:
                heat = db.execute('''SELECT h.id FROM race_heats h
                    JOIN races r ON r.id=h.race_id WHERE h.id=? AND r.project_id=?''',
                                  (heat_id, project_id)).fetchone()
                if heat is None:
                    raise RevisionError('revision_not_found')
            existing = db.execute('SELECT id FROM revision_workspaces WHERE project_id=? AND heat_id IS ?',
                                  (project_id, heat_id)).fetchone()
            if existing is not None:
                return existing['id']
            identity = uuid.uuid4().hex
            db.execute('INSERT INTO revision_workspaces(id,project_id,heat_id) VALUES (?,?,?)',
                       (identity, project_id, heat_id))
            return identity

    def bootstrap(self, owner: str, workspace_id: str, artifact: Artifact) -> str:
        _identifiers(owner, workspace_id)
        _artifact(artifact)
        with self._transaction() as db:
            workspace = self._workspace(db, owner, workspace_id)
            root = db.execute('''SELECT r.*,a.size FROM revision_records r
                JOIN revision_artifacts a ON a.key=r.artifact_key
                WHERE workspace_id=? AND parent_revision_id IS NULL''', (workspace_id,)).fetchone()
            if root is not None:
                if (root['artifact_key'], root['snapshot_revision'], root['size']) != (artifact.key, artifact.revision, artifact.size):
                    raise RevisionError('revision_conflict')
                return root['id']
            if workspace['current_revision_id'] is not None or workspace['active_attempt_id'] is not None:
                raise RevisionError('revision_conflict')
            self._store_metadata(db, artifact)
            revision = uuid.uuid4().hex
            db.execute('INSERT INTO revision_records VALUES (?,?,?,NULL,?,?,NULL,?)',
                       (revision, workspace_id, workspace['project_id'], artifact.key, artifact.revision, int(time.time())))
            db.execute('UPDATE revision_workspaces SET current_revision_id=? WHERE id=?', (revision, workspace_id))
            return revision

    @staticmethod
    def _view(db, attempt):
        base = db.execute('SELECT artifact_key,snapshot_revision FROM revision_records WHERE id=? AND workspace_id=?',
                          (attempt['base_revision_id'],attempt['workspace_id'])).fetchone()
        if base is None or type(attempt['created_at']) is not int:
            raise RevisionError('revision_conflict')
        return Attempt(attempt['id'],attempt['workspace_id'],attempt['run_id'],attempt['generation'],
            attempt['base_revision_id'],attempt['deadline'],attempt['broker_attempt_id'],attempt['grant_id'],
            attempt['created_at'],attempt['project_id'],base['artifact_key'],base['snapshot_revision'])

    def reserve(self, owner: str, workspace_id: str, run_id: str, attempt_id: str,
                grant_id: str, deadline: int) -> Attempt:
        """Persist dispatch identity before the coordinator requests a worker."""
        _identifiers(owner, workspace_id, run_id, attempt_id, grant_id)
        if any(not _GRANT_ID.fullmatch(value) for value in (run_id,attempt_id,grant_id)):
            raise RevisionError('invalid_revision_request')
        if type(deadline) is not int:
            raise RevisionError('invalid_revision_request')
        with self._transaction() as db:
            now = int(time.time())
            if not now < deadline <= now + 7200:
                raise RevisionError('revision_conflict')
            workspace = self._workspace(db, owner, workspace_id)
            if not _GRANT_ID.fullmatch(workspace['project_id']):
                raise RevisionError('invalid_revision_request')
            self._current_run(db, workspace, run_id)
            existing = db.execute('SELECT * FROM revision_attempts WHERE id=?', (attempt_id,)).fetchone()
            if existing is not None:
                if tuple(existing[key] for key in ('workspace_id','run_id','grant_id','deadline')) != (
                        workspace_id, run_id, grant_id, deadline):
                    raise RevisionError('revision_conflict')
                self._active(db, existing, workspace)
                return self._view(db, existing)
            if (workspace['current_revision_id'] is None or workspace['active_attempt_id'] is not None
                    or workspace['generation'] >= 9223372036854775807):
                raise RevisionError('revision_conflict')
            generation = workspace['generation'] + 1
            db.execute('''INSERT INTO revision_attempts
                (id,workspace_id,project_id,run_id,generation,base_revision_id,broker_attempt_id,grant_id,
                 deadline,state,termination_state,created_at) VALUES (?,?,?,?,?,?,?,?,?,'active','pending',?)''',
                (attempt_id,workspace_id,workspace['project_id'],run_id,generation,workspace['current_revision_id'],
                 None,grant_id,deadline,now))
            db.execute('UPDATE revision_workspaces SET generation=?,active_attempt_id=? WHERE id=?',
                       (generation, attempt_id, workspace_id))
            return self._view(db,db.execute('SELECT * FROM revision_attempts WHERE id=?',(attempt_id,)).fetchone())

    def execution(self, owner: str, attempt_id: str) -> Attempt:
        """Reload exact persisted dispatch inputs, only while still authorized."""
        _identifiers(owner,attempt_id)
        with self._transaction() as db:
            attempt, workspace = self._attempt(db,owner,attempt_id)
            self._active(db,attempt,workspace)
            return self._view(db,attempt)

    def completion(self, owner: str, attempt_id: str) -> Attempt:
        """Reload checkpoint authority, including a committed but unclosed receipt."""
        _identifiers(owner, attempt_id)
        with self._transaction() as db:
            attempt, workspace = self._attempt(db, owner, attempt_id)
            receipt = self._receipt(db, attempt_id, workspace['id'])
            self._active(db, attempt, workspace, registered_head=receipt.revision_id if receipt else None)
            if attempt['broker_attempt_id'] is None:
                raise RevisionError('revision_conflict')
            return self._view(db, attempt)

    def bind(self, owner: str, attempt_id: str, broker_attempt_id: str) -> Attempt:
        """Bind one observed broker identity without granting fresh execution."""
        _identifiers(owner,attempt_id,broker_attempt_id)
        with self._transaction() as db:
            attempt, workspace = self._attempt(db,owner,attempt_id)
            self._active(db,attempt,workspace)
            if attempt['broker_attempt_id'] is not None:
                if attempt['broker_attempt_id'] != broker_attempt_id:
                    raise RevisionError('revision_conflict')
                return self._view(db,attempt)
            db.execute('UPDATE revision_attempts SET broker_attempt_id=? WHERE id=?', (broker_attempt_id,attempt_id))
            return self._view(db,db.execute('SELECT * FROM revision_attempts WHERE id=?',(attempt_id,)).fetchone())

    @staticmethod
    def _insert_outbox(db, workspace_id, revision_id, now):
        db.execute("INSERT INTO revision_outbox VALUES (?,?,?,'revision.registered',?,NULL)",
                   (uuid.uuid4().hex, workspace_id, revision_id, now))

    def register(self, owner: str, attempt_id: str, broker_attempt_id: str, grant_id: str,
                 artifact: Artifact) -> Receipt:
        _identifiers(owner, attempt_id, broker_attempt_id, grant_id)
        _artifact(artifact)
        request_hash = hashlib.sha256(json.dumps([broker_attempt_id, grant_id, artifact.key,
            artifact.revision, artifact.size], separators=(',', ':')).encode()).hexdigest()
        with self._transaction() as db:
            attempt, workspace = self._attempt(db, owner, attempt_id)
            if (attempt['broker_attempt_id'], attempt['grant_id']) != (broker_attempt_id, grant_id):
                raise RevisionError('revision_conflict')
            old = db.execute('SELECT * FROM revision_receipts WHERE attempt_id=?', (attempt_id,)).fetchone()
            if old is not None:
                if old['request_hash'] != request_hash:
                    raise RevisionError('revision_conflict')
                return Receipt(attempt_id, workspace['id'], old['revision_id'], artifact.key, artifact.revision)
            self._active(db, attempt, workspace)
            self._store_metadata(db, artifact)
            revision, now = uuid.uuid4().hex, int(time.time())
            db.execute('INSERT INTO revision_records VALUES (?,?,?,?,?,?,?,?)',
                (revision, workspace['id'], workspace['project_id'], attempt['base_revision_id'],
                 artifact.key, artifact.revision, attempt_id, now))
            db.execute('INSERT INTO revision_receipts VALUES (?,?,?,?,?)',
                       (attempt_id, workspace['id'], revision, request_hash, now))
            self._insert_outbox(db, workspace['id'], revision, now)
            self._active(db, attempt, workspace)
            db.execute('UPDATE revision_workspaces SET current_revision_id=? WHERE id=?', (revision, workspace['id']))
            return Receipt(attempt_id, workspace['id'], revision, artifact.key, artifact.revision)

    def receipt(self, owner: str, attempt_id: str, broker_attempt_id: str, grant_id: str) -> Receipt | None:
        """Resolve a lost acknowledgement without replaying storage or promotion."""
        _identifiers(owner, attempt_id, broker_attempt_id, grant_id)
        with self._transaction() as db:
            attempt, workspace = self._attempt(db, owner, attempt_id)
            if (attempt['broker_attempt_id'], attempt['grant_id']) != (broker_attempt_id, grant_id):
                raise RevisionError('revision_conflict')
            return self._receipt(db, attempt_id, workspace['id'])

    @staticmethod
    def _receipt(db, attempt_id, workspace_id):
        row = db.execute('''SELECT c.revision_id,r.artifact_key,r.snapshot_revision FROM revision_receipts c
            JOIN revision_records r ON r.id=c.revision_id WHERE c.attempt_id=?''', (attempt_id,)).fetchone()
        if row is None:
            return None
        return Receipt(attempt_id, workspace_id, row['revision_id'], row['artifact_key'], row['snapshot_revision'])

    def _recovery(self, db, attempt):
        return Recovery(attempt['id'], attempt['workspace_id'], attempt['grant_id'],
            attempt['broker_attempt_id'], attempt['deadline'], attempt['state'],
            attempt['termination_state'], attempt['outcome'],
            self._receipt(db, attempt['id'], attempt['workspace_id']))

    def recovery(self, owner: str, attempt_id: str) -> Recovery:
        """Inspect durable cleanup state without granting execution or closure."""
        _identifiers(owner, attempt_id)
        with self._transaction() as db:
            attempt, _ = self._attempt(db, owner, attempt_id)
            return self._recovery(db, attempt)

    def authorize_capability(self, owner: str, attempt_id: str, *, grant_id: str,
                             project_id: str, run_id: str, generation: int, base_revision: str,
                             issued_at: int, deadline: int) -> Recovery:
        """Compare already cryptographically verified claims to durable identity."""
        _identifiers(owner, attempt_id)
        with self._transaction() as db:
            attempt, _ = self._attempt(db, owner, attempt_id)
            persisted = self._view(db, attempt)
            if (any(type(value) is not int for value in (generation, issued_at, deadline))
                    or persisted.broker_attempt_id is None
                    or (grant_id,project_id,run_id,generation,base_revision,issued_at,deadline) !=
                    (persisted.grant_id,persisted.project_id,persisted.run_id,persisted.generation,
                     persisted.base_revision,persisted.issued_at,persisted.deadline)):
                raise RevisionError('revision_conflict')
            return self._recovery(db, attempt)

    def cancel(self, owner: str, attempt_id: str) -> Recovery:
        """Commit cancellation unless an earlier terminal decision already won."""
        _identifiers(owner, attempt_id)
        with self._transaction() as db:
            attempt, _ = self._attempt(db, owner, attempt_id)
            if attempt['state'] != 'closed' and attempt['outcome'] is None:
                db.execute("UPDATE revision_attempts SET state='cancel_requested',outcome='cancelled' WHERE id=?", (attempt_id,))
                attempt = db.execute('SELECT * FROM revision_attempts WHERE id=?', (attempt_id,)).fetchone()
            return self._recovery(db, attempt)

    def decide_termination(self, owner: str, attempt_id: str, outcome: str) -> Recovery:
        """Persist a terminal decision; confirmation is still a separate fact."""
        _identifiers(owner, attempt_id)
        if outcome not in ('succeeded','failed','cancelled','timed_out'):
            raise RevisionError('invalid_revision_request')
        with self._transaction() as db:
            attempt, workspace = self._attempt(db, owner, attempt_id)
            if attempt['state'] == 'closed':
                return self._recovery(db, attempt)
            if workspace['active_attempt_id'] != attempt_id or workspace['generation'] != attempt['generation']:
                raise RevisionError('revision_conflict')
            if attempt['outcome'] is not None:
                return self._recovery(db, attempt)
            if outcome == 'succeeded':
                receipt = self._receipt(db, attempt_id, workspace['id'])
                if receipt is None:
                    raise RevisionError('revision_conflict')
                self._active(db, attempt, workspace, registered_head=receipt.revision_id)
            state = 'active' if outcome == 'succeeded' else 'cancel_requested'
            db.execute('UPDATE revision_attempts SET state=?,outcome=? WHERE id=?', (state,outcome,attempt_id))
            attempt = db.execute('SELECT * FROM revision_attempts WHERE id=?', (attempt_id,)).fetchone()
            return self._recovery(db, attempt)

    def observe_termination(self, owner: str, attempt_id: str, *, confirmed: bool, outcome: str) -> None:
        """Persist a trusted coordinator observation; does not terminate a worker."""
        _identifiers(owner, attempt_id)
        if type(confirmed) is not bool or outcome not in ('succeeded','failed','cancelled','timed_out'):
            raise RevisionError('invalid_revision_request')
        with self._transaction() as db:
            attempt, workspace = self._attempt(db, owner, attempt_id)
            if attempt['state'] == 'closed':
                if not confirmed or attempt['outcome'] != outcome:
                    raise RevisionError('revision_conflict')
                return
            if workspace['active_attempt_id'] != attempt_id or workspace['generation'] != attempt['generation']:
                raise RevisionError('revision_conflict')
            if attempt['outcome'] is not None and attempt['outcome'] != outcome:
                raise RevisionError('revision_conflict')
            if not confirmed:
                db.execute("UPDATE revision_attempts SET state='cancel_requested',termination_state='unknown' WHERE id=?", (attempt_id,))
                return
            receipt = db.execute('SELECT 1 FROM revision_receipts WHERE attempt_id=?', (attempt_id,)).fetchone()
            if outcome == 'succeeded' and (receipt is None or
                    (attempt['state'] != 'active' and attempt['outcome'] != 'succeeded')):
                raise RevisionError('revision_conflict')
            db.execute("""UPDATE revision_attempts SET state='closed',termination_state='confirmed',outcome=?,closed_at=?
                WHERE id=?""", (outcome, int(time.time()), attempt_id))
            db.execute('UPDATE revision_workspaces SET active_attempt_id=NULL WHERE id=? AND active_attempt_id=?',
                       (workspace['id'], attempt_id))
