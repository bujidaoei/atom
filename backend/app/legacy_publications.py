"""Explicit import of a live legacy site into immutable release history.

Run only against a quiesced database and published-file backup. A mismatch fails
closed: importing a draft that differs from the old public bytes would silently
change an existing URL.
"""
import argparse
from contextlib import closing
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import ssl
import stat
import sys
import uuid

from .artifacts import ArtifactError, SnapshotStore
from .cos_artifacts import CosArtifactStore
from .ip_ingress import IngressError, probe_ip_routes
from .project_origins import OriginRoute, ProjectOriginError, ProjectOriginRepository
from .release_repository import ReleaseRepository, ReleaseReceipt
from .snapshots import SnapshotError, verify_snapshot
from .storage_config import ObjectStorageSettings
from .verification_repository import VerificationError


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


def _readiness(database: Path, project_id: str, address: str,
               first_port: int, last_port: int, ca_file: Path | None):
    origins = ProjectOriginRepository(database, first_port=first_port,
                                      last_port=last_port)
    pair = origins.for_project(project_id)
    if pair is None:
        raise LegacyPublicationError('legacy_import_origin_required')
    context = ssl.create_default_context(cafile=str(ca_file) if ca_file else None)

    def check():
        probe_ip_routes((OriginRoute(project_id, 'preview', pair.preview_port),
                         OriginRoute(project_id, 'public', pair.public_port)),
                        address, tls_context=context, timeout_seconds=3)
    return check


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Inspect or import an exact legacy publication')
    parser.add_argument('--database', required=True, type=Path)
    parser.add_argument('--published-root', required=True, type=Path)
    parser.add_argument('--project-id', required=True)
    parser.add_argument('--slug', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expect-revision')
    parser.add_argument('--expect-artifact')
    parser.add_argument('--address')
    parser.add_argument('--first-port', type=int)
    parser.add_argument('--last-port', type=int)
    parser.add_argument('--ca-file', type=Path)
    args = parser.parse_args(argv)
    if (not args.database.is_absolute() or not args.published_root.is_absolute()
            or (args.apply and (not args.expect_revision or not args.expect_artifact
                or not args.address or args.first_port is None or args.last_port is None))):
        parser.error('absolute paths and exact revision/artifact/ingress inputs are required')
    if args.apply and args.ca_file is not None and not args.ca_file.is_absolute():
        parser.error('CA path must be absolute')
    try:
        settings = ObjectStorageSettings()
        if settings.storage_backend != 'cos':
            raise LegacyPublicationError('legacy_import_cos_required')
        store = CosArtifactStore(settings)
        candidate = inspect_live_legacy(args.database, args.published_root, store,
                                        project_id=args.project_id, slug=args.slug)
        if not args.apply:
            print(json.dumps(candidate.__dict__, sort_keys=True))
            return 0
        if (candidate.revision_id != args.expect_revision
                or candidate.artifact_key != args.expect_artifact):
            raise LegacyPublicationError('legacy_import_expectation_changed')
        readiness = _readiness(args.database, args.project_id, args.address,
                               args.first_port, args.last_port, args.ca_file)
        receipt = import_live_legacy(args.database, args.published_root, store,
                                     project_id=args.project_id, slug=args.slug,
                                     readiness=readiness)
        print(json.dumps(receipt.__dict__, sort_keys=True))
        return 0
    except (LegacyPublicationError, ProjectOriginError, IngressError, ArtifactError,
            VerificationError, SnapshotError, OSError, ValueError, sqlite3.Error) as error:
        code = (str(error) if isinstance(error, (LegacyPublicationError, ProjectOriginError,
                                                 IngressError, ArtifactError, VerificationError,
                                                 SnapshotError)) else 'legacy_import_unavailable')
        print(json.dumps({'error': code}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
