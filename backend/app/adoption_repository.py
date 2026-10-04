"""Fenced adoption of an immutable, verified race-heat revision."""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from threading import BoundedSemaphore
import time
import uuid

from .artifacts import Artifact, ArtifactError, ArtifactStore, _describe
from .migrations import MigrationError, _schema, verify


_ID = re.compile(r'[A-Za-z0-9_-]{1,128}\Z')
_READ_SLOTS = BoundedSemaphore(1)


class AdoptionError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class AdoptionReceipt:
    command_id: str
    project_id: str
    source_revision_id: str
    revision_id: str
    artifact: Artifact


@dataclass(frozen=True)
class _Candidate:
    race_id: str
    source_workspace_id: str
    target_workspace_id: str
    target_generation: int
    artifact: Artifact


class AdoptionRepository:
    def __init__(self, path: Path, *, lock_timeout: float = 3):
        if isinstance(lock_timeout, bool) or not isinstance(lock_timeout, (float, int)) or not 0 < lock_timeout <= 10:
            raise AdoptionError('invalid_adoption_configuration')
        self.path, self.timeout = Path(path), lock_timeout
        try:
            if verify(self.path) not in (12, 13, 14, 15, 16, 17, 18, 19):
                raise AdoptionError('adoption_schema_required')
        except MigrationError:
            raise AdoptionError('adoption_schema_required') from None

    @contextmanager
    def _transaction(self):
        db = None
        try:
            db = sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True,
                                 timeout=self.timeout, isolation_level=None)
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            if _schema(db) not in (12, 13, 14, 15, 16, 17, 18, 19):
                raise AdoptionError('adoption_schema_required')
            db.row_factory = sqlite3.Row
            yield db
            db.execute('COMMIT')
        except sqlite3.IntegrityError:
            raise AdoptionError('adoption_conflict') from None
        except (sqlite3.Error, OSError, MigrationError):
            raise AdoptionError('adoption_unavailable') from None
        finally:
            if db is not None:
                if db.in_transaction:
                    db.rollback()
                db.close()

    @staticmethod
    def _receipt(db, command_id: str, digest: str, project_id: str) -> AdoptionReceipt | None:
        row = db.execute('''SELECT a.*,v.id AS revision_id,v.artifact_key,v.snapshot_revision,
                   artifact.size FROM revision_adoptions a
                   LEFT JOIN revision_records v ON v.adoption_id=a.id
                   LEFT JOIN revision_artifacts artifact ON artifact.key=v.artifact_key
                       AND artifact.revision=v.snapshot_revision
                   WHERE a.id=?''', (command_id,)).fetchone()
        if row is None:
            return None
        if row['project_id'] != project_id or row['request_hash'] != digest:
            raise AdoptionError('adoption_conflict')
        if row['revision_id'] is None or row['size'] is None:
            raise AdoptionError('adoption_corrupt')
        return AdoptionReceipt(command_id, project_id, row['source_revision_id'], row['revision_id'],
                               Artifact(row['artifact_key'], row['snapshot_revision'], row['size']))

    @staticmethod
    def _candidate(db, owner: str, project_id: str, heat_id: str, source_revision_id: str,
                   expected_main_revision_id: str | None) -> _Candidate:
        row = db.execute('''SELECT race.id AS race_id,race.status AS race_status,
                   heat.status AS heat_status,project.active_run_id,
                   source.id AS source_workspace_id,source.current_revision_id AS source_head,
                   source.active_attempt_id AS source_attempt,
                   target.id AS target_workspace_id,target.current_revision_id AS target_head,
                   target.active_attempt_id AS target_attempt,target.generation AS target_generation,
                   revision.artifact_key,revision.snapshot_revision,artifact.size
                   FROM projects project
                   JOIN races race ON race.project_id=project.id
                   JOIN race_heats heat ON heat.race_id=race.id AND heat.id=?
                   JOIN revision_workspaces source ON source.project_id=project.id AND source.heat_id=heat.id
                   JOIN revision_workspaces target ON target.project_id=project.id AND target.heat_id IS NULL
                   LEFT JOIN revision_records revision ON revision.id=source.current_revision_id
                       AND revision.workspace_id=source.id
                   LEFT JOIN revision_artifacts artifact ON artifact.key=revision.artifact_key
                       AND artifact.revision=revision.snapshot_revision
                   WHERE project.id=? AND project.user_id=?''', (heat_id, project_id, owner)).fetchone()
        if row is None:
            raise AdoptionError('adoption_not_found')
        if (row['race_status'] != 'done' or row['heat_status'] != 'done'
                or row['active_run_id'] is not None or row['source_attempt'] is not None
                or row['target_attempt'] is not None or row['source_head'] != source_revision_id
                or row['target_head'] != expected_main_revision_id
                or row['artifact_key'] is None or row['snapshot_revision'] is None or row['size'] is None):
            raise AdoptionError('adoption_conflict')
        if db.execute('''SELECT 1 FROM revision_attempts WHERE workspace_id IN (?,?)
                       AND termination_state!='confirmed' LIMIT 1''',
                      (row['source_workspace_id'], row['target_workspace_id'])).fetchone():
            raise AdoptionError('adoption_conflict')
        return _Candidate(row['race_id'], row['source_workspace_id'], row['target_workspace_id'],
                          row['target_generation'],
                          Artifact(row['artifact_key'], row['snapshot_revision'], row['size']))

    def adopt(self, *, owner: str, project_id: str, heat_id: str, source_revision_id: str,
              expected_main_revision_id: str | None, command_id: str, store: ArtifactStore) -> AdoptionReceipt:
        values = (owner, project_id, heat_id, source_revision_id, expected_main_revision_id, command_id)
        if (any(not isinstance(value, str) or not _ID.fullmatch(value)
                for value in (owner, project_id, heat_id, source_revision_id, command_id))
                or (expected_main_revision_id is not None and
                    (not isinstance(expected_main_revision_id, str) or
                     not _ID.fullmatch(expected_main_revision_id)))):
            raise AdoptionError('invalid_adoption_request')
        if not callable(getattr(store, 'read', None)):
            raise AdoptionError('invalid_adoption_request')
        digest = hashlib.sha256(json.dumps(values, separators=(',', ':')).encode()).hexdigest()
        with self._transaction() as db:
            if db.execute('SELECT 1 FROM projects WHERE id=? AND user_id=?', (project_id, owner)).fetchone() is None:
                raise AdoptionError('adoption_not_found')
            replay = self._receipt(db, command_id, digest, project_id)
            if replay is not None:
                return replay
            candidate = self._candidate(db, owner, project_id, heat_id, source_revision_id,
                                        expected_main_revision_id)
        if not _READ_SLOTS.acquire(timeout=3):
            raise AdoptionError('adoption_capacity')
        try:
            try:
                verified = _describe(store.read(candidate.artifact.key))
            except (ArtifactError, OSError):
                raise AdoptionError('adoption_artifact_unavailable') from None
            if verified != candidate.artifact:
                raise AdoptionError('adoption_artifact_mismatch')
            with self._transaction() as db:
                replay = self._receipt(db, command_id, digest, project_id)
                if replay is not None:
                    return replay
                current = self._candidate(db, owner, project_id, heat_id, source_revision_id,
                                          expected_main_revision_id)
                if current != candidate:
                    raise AdoptionError('adoption_conflict')
                now, revision_id = int(time.time()), uuid.uuid4().hex
                parent_id = expected_main_revision_id
                target_generation = candidate.target_generation
                if parent_id is None:
                    # Schema v12+ requires a parent for adoption provenance. Seed the
                    # empty main workspace from the same verified artifact inside this
                    # transaction, then adopt the heat over that root. No intermediate
                    # revision is observable if any later fence fails.
                    parent_id = uuid.uuid4().hex
                    db.execute('''INSERT INTO revision_records
                               (id,workspace_id,project_id,parent_revision_id,artifact_key,snapshot_revision,
                                producing_attempt_id,created_at,adoption_id)
                               VALUES (?,?,?,NULL,?,?,NULL,?,NULL)''',
                               (parent_id, candidate.target_workspace_id, project_id,
                                candidate.artifact.key, candidate.artifact.revision, now))
                    db.execute("INSERT INTO revision_outbox VALUES (?,?,?,'revision.registered',?,NULL)",
                               (uuid.uuid4().hex, candidate.target_workspace_id, parent_id, now))
                    seeded = db.execute('''UPDATE revision_workspaces
                               SET current_revision_id=?,generation=generation+1
                               WHERE id=? AND current_revision_id IS NULL AND generation=?
                                 AND active_attempt_id IS NULL''',
                               (parent_id, candidate.target_workspace_id, target_generation))
                    if seeded.rowcount != 1:
                        raise AdoptionError('adoption_conflict')
                    target_generation += 1
                db.execute('''INSERT INTO revision_adoptions VALUES (?,?,?,?,?,?,?,?,?,?)''',
                           (command_id, project_id, heat_id, candidate.source_workspace_id,
                            source_revision_id, candidate.target_workspace_id, parent_id,
                            owner, digest, now))
                db.execute('''INSERT INTO revision_records
                           (id,workspace_id,project_id,parent_revision_id,artifact_key,snapshot_revision,
                            producing_attempt_id,created_at,adoption_id)
                           VALUES (?,?,?,?,?,?,NULL,?,?)''',
                           (revision_id, candidate.target_workspace_id, project_id, parent_id,
                            candidate.artifact.key, candidate.artifact.revision, now, command_id))
                db.execute("INSERT INTO revision_outbox VALUES (?,?,?,'revision.registered',?,NULL)",
                           (uuid.uuid4().hex, candidate.target_workspace_id, revision_id, now))
                updated = db.execute('''UPDATE revision_workspaces SET current_revision_id=?,generation=generation+1
                           WHERE id=? AND current_revision_id=? AND generation=? AND active_attempt_id IS NULL''',
                           (revision_id, candidate.target_workspace_id, parent_id,
                            target_generation))
                if updated.rowcount != 1:
                    raise AdoptionError('adoption_conflict')
                updated = db.execute("UPDATE races SET winner_heat_id=? WHERE id=? AND status='done'",
                                     (heat_id, candidate.race_id))
                if updated.rowcount != 1:
                    raise AdoptionError('adoption_conflict')
                updated = db.execute("""UPDATE projects SET status='ready',updated_at=?
                           WHERE id=? AND user_id=? AND active_run_id IS NULL""",
                                     (datetime.now(timezone.utc).isoformat(), project_id, owner))
                if updated.rowcount != 1:
                    raise AdoptionError('adoption_conflict')
                return AdoptionReceipt(command_id, project_id, source_revision_id, revision_id,
                                       candidate.artifact)
        finally:
            _READ_SLOTS.release()
