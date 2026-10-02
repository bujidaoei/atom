"""Read-only audit of a schema10→18 rehearsal and its predecessor backups."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys

from .migrations import MigrationError, verify_backup


_COUNT_TABLES = ('projects', 'revision_records', 'revision_artifacts',
                 'release_publications')


def _counts(path: Path) -> dict[str, int]:
    try:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True,
                                     timeout=3)) as db:
            db.execute('PRAGMA query_only=ON')
            return {table: db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                    for table in _COUNT_TABLES}
    except (OSError, sqlite3.Error):
        raise MigrationError('migration_audit_unavailable') from None


def audit(database: Path, backup_dir: Path) -> dict:
    """Require every verified predecessor and unchanged business-row counts."""
    if (not isinstance(database, Path) or not isinstance(backup_dir, Path)
            or not database.is_absolute() or not backup_dir.is_absolute()
            or database.is_symlink() or backup_dir.is_symlink()
            or not backup_dir.is_dir()):
        raise MigrationError('invalid_migration_audit_path')
    digest = verify_backup(database, expected_version=18)
    backups = {}
    for target in range(11, 19):
        predecessor = backup_dir / f'before-v{target}.db'
        backups[target] = verify_backup(predecessor, expected_version=target - 1)
    baseline = _counts(backup_dir / 'before-v11.db')
    current = _counts(database)
    if current != baseline:
        raise MigrationError('migration_business_counts_changed')
    try:
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True,
                                     timeout=3)) as db:
            db.execute('PRAGMA query_only=ON')
            journal = dict(db.execute('SELECT version,backup_sha256 '
                                      'FROM atom_schema_migrations WHERE version BETWEEN 11 AND 18'))
    except (OSError, sqlite3.Error):
        raise MigrationError('migration_audit_unavailable') from None
    if journal != backups:
        raise MigrationError('migration_backup_chain_mismatch')
    return {'version':18, 'databaseSha256':digest, 'counts':current,
            'predecessorVersions':list(backups)}


def main() -> int:
    parser = argparse.ArgumentParser(description='Audit an isolated schema10→18 rehearsal')
    parser.add_argument('database', type=Path)
    parser.add_argument('--backup-dir', required=True, type=Path)
    arguments = parser.parse_args()
    try:
        print(json.dumps(audit(arguments.database, arguments.backup_dir), sort_keys=True))
    except MigrationError as error:
        print(json.dumps({'error':error.code}), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
