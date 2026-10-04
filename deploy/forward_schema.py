"""Explicit supported source schemas for protected forward deployment."""
from pathlib import Path
from contextlib import closing
import sqlite3
import protected_cutover


def version(path: Path) -> int:
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=3)) as db:
        value = db.execute('PRAGMA user_version').fetchone()[0]
    if value not in (18, 19):
        raise protected_cutover.CutoverError('schema_mismatch')
    return value


def migrate_candidate(path: Path, *, target: int):
    """Called only after a verified pair restore, before candidate writers start."""
    from app.migrations import migrate, verify
    source = version(path)
    if target not in (18, 19) or source > target:
        raise ValueError('unsupported_forward_schema_transition')
    if source == target:
        return
    backup = path.parent / 'before-contract-v19.db'
    migrate(path, backup, target_version=target)
    if verify(path) != target:
        raise ValueError('forward_migration_not_verified')
