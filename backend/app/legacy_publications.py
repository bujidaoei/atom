"""Explicit import of a live legacy site into immutable release history.

Run only against a quiesced database and published-file backup. A mismatch fails
closed: importing a draft that differs from the old public bytes would silently
change an existing URL.
"""
from contextlib import closing
from dataclasses import dataclass
import hashlib
import io
from pathlib import Path
import sqlite3
import stat
import uuid

from .artifacts import SnapshotStore
from .release_repository import ReleaseRepository, ReleaseReceipt
from .snapshots import verify_snapshot


class LegacyPublicationError(RuntimeError):
    pass


@dataclass(frozen=True)
class LegacyImport:
    project_id: str
    slug: str
    owner: str
    revision_id: str
    file_count: int
    artifact_key: str


def inspect_live_legacy(database: Path, published_root: Path, store: SnapshotStore,
                        *, project_id: str, slug: str) -> LegacyImport:
    """Prove that old public bytes equal the current registered saved revision."""
    with closing(sqlite3.connect(Path(database).as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        if db.execute('PRAGMA user_version').fetchone()[0] not in (17, 18):
            raise LegacyPublicationError('legacy_import_schema_required')
        row = db.execute('''SELECT p.slug,p.live,p.project_id,o.user_id,o.status,o.active_run_id,
                    w.id AS workspace_id,w.current_revision_id,w.active_attempt_id,
                    r.artifact_key,r.snapshot_revision,a.size
                FROM publications p JOIN projects o ON o.id=p.project_id
                JOIN revision_workspaces w ON w.project_id=p.project_id AND w.heat_id IS NULL
                JOIN revision_records r ON r.id=w.current_revision_id AND r.workspace_id=w.id
                JOIN revision_artifacts a ON a.key=r.artifact_key AND a.revision=r.snapshot_revision
                WHERE p.project_id=? AND p.slug=?''', (project_id, slug)).fetchone()
        if (row is None or row['live'] != 1 or row['status'] != 'ready'
                or row['active_run_id'] is not None or row['active_attempt_id'] is not None):
            raise LegacyPublicationError('legacy_import_not_ready')
        if db.execute('SELECT 1 FROM release_publications WHERE project_id=?',
                      (project_id,)).fetchone() is not None:
            raise LegacyPublicationError('legacy_import_already_present')
        ports = db.execute('SELECT purpose FROM project_origin_ports WHERE project_id=?',
                           (project_id,)).fetchall()
        if {p[0] for p in ports} != {'preview', 'public'} or len(ports) != 2:
            raise LegacyPublicationError('legacy_import_origin_required')
        artifact_key, revision, size = row['artifact_key'], row['snapshot_revision'], row['size']
        result = LegacyImport(project_id, slug, row['user_id'], row['current_revision_id'],
                              0, artifact_key)
    payload = store.read(artifact_key)
    if hashlib.sha256(payload).hexdigest() != artifact_key or len(payload) != size:
        raise LegacyPublicationError('legacy_import_artifact_mismatch')
    manifest = verify_snapshot(io.BytesIO(payload))
    if manifest.revision != revision:
        raise LegacyPublicationError('legacy_import_artifact_mismatch')
    directory = Path(published_root) / slug
    if directory.is_symlink() or not directory.is_dir():
        raise LegacyPublicationError('legacy_import_files_mismatch')
    actual = {}
    for path in directory.rglob('*'):
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise LegacyPublicationError('legacy_import_files_mismatch')
        actual[path.relative_to(directory).as_posix()] = (info.st_size,
            hashlib.sha256(path.read_bytes()).hexdigest())
    expected = {entry.path: (entry.size, entry.sha256) for entry in manifest.files}
    if actual != expected:
        raise LegacyPublicationError('legacy_import_files_mismatch')
    return LegacyImport(result.project_id, result.slug, result.owner, result.revision_id,
                        len(expected), result.artifact_key)


def import_live_legacy(database: Path, published_root: Path, store: SnapshotStore,
                       *, project_id: str, slug: str, readiness) -> ReleaseReceipt:
    """Promote only the inspected exact snapshot through the normal release path."""
    if not callable(readiness):
        raise LegacyPublicationError('legacy_import_readiness_required')
    candidate = inspect_live_legacy(database, published_root, store,
                                    project_id=project_id, slug=slug)
    return ReleaseRepository(database, required_schema=17).publish_snapshot(
        store, owner=candidate.owner, project_id=project_id, release_id=uuid.uuid4().hex,
        expected_revision=candidate.revision_id, expected_generation=0,
        audience='public', slug=slug, readiness=readiness)
