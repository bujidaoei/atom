"""Prepare a disposable copy of a quiesced schema-10 ledger for IP publication.

The caller keeps the verified old-image backup immutable. A failed preparation
invalidates this copy; recreate it from that backup rather than resuming a
partly migrated ledger.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3
import sys

from .migration_audit import audit
from .migrations import MigrationError, migrate, verify_backup
from .project_origins import ProjectOriginError, ProjectOriginRepository


_DIGEST = re.compile(r'[0-9a-f]{64}\Z')


class PreparationError(RuntimeError):
    """Stable operator error code without project data or credentials."""


def _counts(database: Path) -> dict[str, int]:
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro&immutable=1',
                                 uri=True, timeout=3)) as connection:
        connection.execute('PRAGMA query_only=ON')
        return {table: connection.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                for table in ('projects', 'revision_records', 'revision_artifacts')}


def prepare(database: Path, backup_dir: Path, *, source_sha256: str,
            expected_counts: dict[str, int], first_port: int,
            last_port: int) -> dict[str, object]:
    if (not isinstance(database, Path) or not database.is_absolute()
            or database.is_symlink() or not isinstance(backup_dir, Path)
            or not backup_dir.is_absolute() or backup_dir.is_symlink()
            or not backup_dir.parent.is_dir() or backup_dir.exists()
            or backup_dir == database or backup_dir in database.parents
            or database in backup_dir.parents or not isinstance(source_sha256, str)
            or _DIGEST.fullmatch(source_sha256) is None
            or type(expected_counts) is not dict
            or set(expected_counts) != {'projects', 'revision_records', 'revision_artifacts'}
            or any(type(value) is not int or value < 0 for value in expected_counts.values())
            or type(first_port) is not int or type(last_port) is not int
            or not 1024 <= first_port < last_port <= 65535
            or last_port - first_port + 1 > 512):
        raise PreparationError('invalid_preparation_input')
    if expected_counts['projects'] * 2 > last_port - first_port + 1:
        raise PreparationError('origin_capacity')
    try:
        if verify_backup(database, expected_version=10, immutable=True) != source_sha256:
            raise PreparationError('source_digest_changed')
        if _counts(database) != expected_counts:
            raise PreparationError('source_counts_changed')
        backup_dir.mkdir(mode=0o700)
        for version in range(11, 19):
            result = migrate(database, backup_dir / f'before-v{version}.db',
                             target_version=version)
            if not result.applied or result.version != version:
                raise PreparationError('migration_step_incomplete')
        migration = audit(database, backup_dir)
        if any(migration['counts'][key] != value
               for key, value in expected_counts.items()):
            raise PreparationError('migration_counts_changed')
        origins = ProjectOriginRepository(database, first_port=first_port,
                                          last_port=last_port).reserve_existing()
        if len(origins) != expected_counts['projects']:
            raise PreparationError('origin_count_changed')
        digest = verify_backup(database, expected_version=18, immutable=True)
        return {'schema': 18, 'databaseSha256': digest, 'counts': migration['counts'],
                'predecessorVersions': migration['predecessorVersions'],
                'originPairs': len(origins), 'firstPort': first_port,
                'lastAllocatedPort': max((item.public_port for item in origins),
                                         default=None)}
    except (MigrationError, ProjectOriginError, OSError, sqlite3.Error) as error:
        code = (error.code if isinstance(error, MigrationError)
                else str(error) if isinstance(error, ProjectOriginError)
                else 'preparation_unavailable')
        raise PreparationError(code) from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, type=Path)
    parser.add_argument('--backup-dir', required=True, type=Path)
    parser.add_argument('--source-sha256', required=True)
    parser.add_argument('--expect-projects', required=True, type=int)
    parser.add_argument('--expect-revisions', required=True, type=int)
    parser.add_argument('--expect-artifacts', required=True, type=int)
    parser.add_argument('--first-port', required=True, type=int)
    parser.add_argument('--last-port', required=True, type=int)
    arguments = parser.parse_args(argv)
    try:
        receipt = prepare(arguments.database, arguments.backup_dir,
                          source_sha256=arguments.source_sha256,
                          expected_counts={'projects': arguments.expect_projects,
                                           'revision_records': arguments.expect_revisions,
                                           'revision_artifacts': arguments.expect_artifacts},
                          first_port=arguments.first_port, last_port=arguments.last_port)
    except PreparationError as error:
        print(json.dumps({'error': str(error)}), file=sys.stderr)
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
