"""Copy a live SQLite database and rehearse the exact publication migrations.

The source is only opened read-only. This is a rehearsal, not production cutover
or an artifact/workspace backup.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import sqlite3

from .migrations import MigrationError, migrate, verify, verify_backup


class RehearsalError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class RehearsalReceipt:
    source_version: int
    final_version: int
    projects: int
    revisions: int
    artifacts: int
    publication_rows: int
    predecessor_backups: int


def _counts(path: Path) -> tuple[int, int, int, int]:
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=3)) as db:
        db.execute('PRAGMA query_only=ON')
        if db.execute('PRAGMA integrity_check').fetchone() != ('ok',):
            raise RehearsalError('rehearsal_integrity_failed')
        if db.execute('PRAGMA foreign_key_check').fetchone() is not None:
            raise RehearsalError('rehearsal_foreign_key_failed')
        return tuple(db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in
                     ('projects', 'revision_records', 'revision_artifacts', 'release_records'))


def rehearse(source: Path, destination: Path, *, expected_version: int = 10) -> RehearsalReceipt:
    if (not isinstance(source, Path) or not source.is_absolute() or source.is_symlink()
            or not source.is_file() or not isinstance(destination, Path)
            or not destination.is_absolute() or destination.exists()
            or destination.is_symlink() or not destination.parent.is_dir()
            or source.resolve().is_relative_to(destination.resolve())
            or type(expected_version) is not int or expected_version != 10):
        raise RehearsalError('invalid_rehearsal_configuration')
    try:
        if verify(source) != expected_version:
            raise RehearsalError('rehearsal_source_schema_changed')
        source_counts = _counts(source)
        destination.mkdir(mode=0o700)
        copy = destination / 'atom.db'
        # SQLite online backup includes committed WAL changes in one consistent DB.
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=10)) as live:
            with closing(sqlite3.connect(copy)) as target:
                live.backup(target, pages=256, sleep=.05)
        # The online source uses WAL. Rehearsal runs without application writers;
        # switch only the isolated copy to rollback journaling before table rebuilds.
        with closing(sqlite3.connect(copy, timeout=3, isolation_level=None)) as target:
            if target.execute('PRAGMA journal_mode=DELETE').fetchone() != ('delete',):
                raise RehearsalError('rehearsal_journal_unavailable')
        if verify(copy) != expected_version or _counts(copy) != source_counts:
            raise RehearsalError('rehearsal_copy_mismatch')
        for version in range(expected_version + 1, 18):
            backup = destination / f'before-v{version}.db'
            result = migrate(copy, backup, target_version=version)
            if not result.applied or verify(copy) != version or\
                    verify_backup(backup, expected_version=version - 1) != result.backup_sha256:
                raise RehearsalError('rehearsal_migration_mismatch')
            if _counts(copy) != source_counts:
                raise RehearsalError('rehearsal_data_changed')
        replay_backup = destination / 'replay-should-not-exist.db'
        replay = migrate(copy, replay_backup, target_version=17)
        if replay.applied or replay.version != 17 or replay_backup.exists():
            raise RehearsalError('rehearsal_replay_mismatch')
        if verify(source) != expected_version:
            raise RehearsalError('rehearsal_source_schema_changed')
        return RehearsalReceipt(expected_version, 17, *source_counts, 7)
    except (sqlite3.Error, OSError, MigrationError):
        raise RehearsalError('rehearsal_unavailable') from None


def main() -> None:
    parser = argparse.ArgumentParser(description='Rehearse schema 10 to 17 on a private SQLite copy')
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    arguments = parser.parse_args()
    old_umask = os.umask(0o077)
    try:
        print(json.dumps(asdict(rehearse(arguments.source, arguments.destination)),
                         sort_keys=True, separators=(',', ':')))
    except RehearsalError as error:
        parser.exit(1, json.dumps({'error': error.code}) + '\n')
    finally:
        os.umask(old_umask)


if __name__ == '__main__':
    main()
