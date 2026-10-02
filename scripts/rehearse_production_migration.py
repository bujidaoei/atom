"""Rehearse v10→v15 on a private copy without mutating the source database."""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys

from app.migrations import migrate, verify, verify_backup


def _read_only(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    db.execute('PRAGMA query_only=ON')
    return db


def _value(value):
    if value is None:
        return ['null']
    if type(value) is bytes:
        return ['bytes', value.hex()]
    if type(value) is str:
        return ['text', value]
    if type(value) is int:
        return ['integer', value]
    if type(value) is float:
        return ['real', repr(value)]
    raise RuntimeError('unsupported_database_value')


def _table_fingerprint(db: sqlite3.Connection, table: str, columns: list[str]):
    quoted_table = '"' + table.replace('"', '""') + '"'
    quoted_columns = ','.join('"' + name.replace('"', '""') + '"' for name in columns)
    row_hashes = []
    for row in db.execute(f'SELECT {quoted_columns} FROM {quoted_table}'):
        encoded = json.dumps([_value(value) for value in row],
                             separators=(',', ':'), ensure_ascii=False).encode('utf-8')
        row_hashes.append(hashlib.sha256(encoded).digest())
    digest = hashlib.sha256(b''.join(sorted(row_hashes))).hexdigest()
    return len(row_hashes), digest


def _inventory(db: sqlite3.Connection):
    tables = [row[0] for row in db.execute("SELECT name FROM sqlite_schema "
              "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
              "AND name!='atom_schema_migrations' ORDER BY name")]
    result = {}
    for table in tables:
        quoted_table = '"' + table.replace('"', '""') + '"'
        columns = [row[1] for row in db.execute(f'PRAGMA table_info({quoted_table})')]
        result[table] = columns
    return result


def rehearse(source: Path, scratch: Path):
    if not source.is_absolute() or source.is_symlink() or not source.is_file():
        raise RuntimeError('invalid_source_database')
    if not scratch.is_absolute() or scratch.is_symlink() or not scratch.is_dir():
        raise RuntimeError('invalid_scratch_directory')
    if ((os.name == 'posix' and stat.S_IMODE(scratch.stat().st_mode) != 0o700)
            or any(scratch.iterdir())):
        raise RuntimeError('scratch_must_be_private_and_empty')
    if source.resolve().is_relative_to(scratch.resolve()):
        raise RuntimeError('source_inside_scratch')
    if verify(source) != 10:
        raise RuntimeError('source_schema_must_be_v10')

    target = scratch / 'atom.db'
    with closing(_read_only(source)) as original, closing(sqlite3.connect(target)) as copied:
        original.backup(copied)
    os.chmod(target, 0o600)
    if verify(target) != 10:
        raise RuntimeError('copy_schema_mismatch')

    with closing(_read_only(source)) as original:
        tables = _inventory(original)
        fingerprints = {table: _table_fingerprint(original, table, columns)
                        for table, columns in tables.items()}
        original_journal = original.execute('SELECT * FROM atom_schema_migrations '
                                            'ORDER BY version').fetchall()

    stages = []
    for version in range(11, 16):
        backup = scratch / f'before-v{version}.db'
        result = migrate(target, backup, target_version=version)
        if not result.applied or result.version != version or verify(target) != version:
            raise RuntimeError(f'migration_v{version}_unverified')
        if verify_backup(backup, expected_version=version - 1) != result.backup_sha256:
            raise RuntimeError(f'backup_v{version}_unverified')
        with closing(_read_only(target)) as db:
            if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise RuntimeError(f'integrity_v{version}_failed')
            if db.execute('PRAGMA foreign_key_check').fetchall():
                raise RuntimeError(f'foreign_keys_v{version}_failed')
        stages.append(version)

    with closing(_read_only(target)) as db:
        current = _inventory(db)
        for table, columns in tables.items():
            if table not in current or not set(columns).issubset(current[table]):
                raise RuntimeError(f'table_structure_changed:{table}')
            if _table_fingerprint(db, table, columns) != fingerprints[table]:
                raise RuntimeError(f'business_rows_changed:{table}')
        retained = db.execute('SELECT * FROM atom_schema_migrations '
                              'WHERE version<=10 ORDER BY version').fetchall()
        if retained != original_journal:
            raise RuntimeError('migration_journal_changed')
    return {'source_version': 10, 'final_version': 15,
            'stages': stages, 'preserved_tables': len(tables)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--scratch', type=Path, required=True)
    arguments = parser.parse_args()
    try:
        print(json.dumps(rehearse(arguments.source, arguments.scratch), sort_keys=True))
    except (OSError, sqlite3.Error, RuntimeError) as error:
        print(json.dumps({'error': str(error)}), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
