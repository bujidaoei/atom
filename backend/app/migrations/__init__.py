"""Explicit versioned API-database migration; never selected by API startup."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

from .revision_v1 import BASELINE_HASH, MIGRATION_HASH, SCHEMA, apply as _apply_revision_schema


class MigrationError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class MigrationResult:
    version: int
    applied: bool
    backup_sha256: str


def _path(value, *, existing):
    path = Path(value)
    if not path.is_absolute() or path.is_symlink() or not path.parent.is_dir() or (existing and not path.is_file()):
        raise MigrationError("invalid_migration_path")
    return path


def _open(path, *, readonly=False, timeout=3):
    db = sqlite3.connect(path.as_uri() + ("?mode=ro" if readonly else "?mode=rw"), uri=True,
                         timeout=timeout, isolation_level=None)
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA synchronous=FULL")
    return db


def _schema(db):
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version not in (0, 1):
        raise MigrationError("unsupported_schema")
    rows = db.execute("SELECT type,name,sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' AND sql IS NOT NULL ORDER BY type,name").fetchall()
    extension = {name: sql for kind, name, sql in rows if name in SCHEMA}
    baseline = [(kind, name, sql) for kind, name, sql in rows if name not in SCHEMA]
    digest = hashlib.sha256(json.dumps(baseline, separators=(",", ":")).encode()).hexdigest()
    if digest != BASELINE_HASH or (version == 0 and extension):
        raise MigrationError("unsupported_schema")
    if version == 1:
        if extension != SCHEMA:
            raise MigrationError("unsupported_schema")
        journal = db.execute("SELECT version,migration_hash,backup_sha256 FROM atom_schema_migrations").fetchall()
        if len(journal) != 1 or journal[0][:2] != (1, MIGRATION_HASH):
            raise MigrationError("unsupported_schema")
    return version


def verify(path: Path) -> int:
    db = None
    try:
        db = _open(_path(path, existing=True), readonly=True)
        return _schema(db)
    except (OSError, sqlite3.Error):
        raise MigrationError("migration_unavailable") from None
    finally:
        if db is not None:
            db.close()


def _digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _integrity(db):
    if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)] or db.execute("PRAGMA foreign_key_check").fetchall():
        raise MigrationError("invalid_database_integrity")


def verify_backup(path: Path) -> str:
    db = None
    try:
        path = _path(path, existing=True)
        db = _open(path, readonly=True)
        if _schema(db) != 0:
            raise MigrationError("invalid_backup_version")
        _integrity(db)
        return _digest(path)
    except (OSError, sqlite3.Error):
        raise MigrationError("backup_unavailable") from None
    finally:
        if db is not None:
            db.close()


def _backup(source, destination):
    descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
    os.close(descriptor)
    reader = target = None
    try:
        reader = _open(source, readonly=True)
        target = sqlite3.connect(destination, isolation_level=None)
        deadline = time.monotonic() + 30
        def progress(*_args):
            if time.monotonic() >= deadline:
                raise MigrationError("backup_timeout")
        reader.backup(target, pages=128, progress=progress, sleep=0.01)
        target.execute("PRAGMA journal_mode=DELETE")
        _integrity(target)
        if _schema(target) != 0:
            raise MigrationError("invalid_backup_version")
    finally:
        if reader is not None:
            reader.close()
        if target is not None:
            target.close()
    with destination.open("r+b") as stream:
        os.fsync(stream.fileno())
    if sys.platform == "linux":
        directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    return verify_backup(destination)


def migrate(path: Path, backup: Path, *, lock_timeout: float = 3) -> MigrationResult:
    if isinstance(lock_timeout, bool) or not isinstance(lock_timeout, (int, float)) or not 0 < lock_timeout <= 10:
        raise MigrationError("invalid_migration_timeout")
    db = None
    try:
        path, backup = _path(path, existing=True), _path(backup, existing=False)
        if path.resolve() == backup.resolve():
            raise MigrationError("invalid_backup_path")
        db = _open(path, timeout=lock_timeout)
        db.execute("BEGIN IMMEDIATE")
        version = _schema(db)
        _integrity(db)
        if version == 1:
            digest = db.execute("SELECT backup_sha256 FROM atom_schema_migrations WHERE version=1").fetchone()[0]
            db.execute("ROLLBACK")
            return MigrationResult(1, False, digest)
        digest = _backup(path, backup)
        _apply_revision_schema(db)
        db.execute("INSERT INTO atom_schema_migrations VALUES (1,?,?,?)", (MIGRATION_HASH, digest, int(time.time())))
        db.execute("PRAGMA user_version=1")
        _schema(db)
        _integrity(db)
        db.execute("COMMIT")
        return MigrationResult(1, True, digest)
    except (OSError, sqlite3.Error):
        raise MigrationError("migration_failed") from None
    finally:
        if db is not None:
            if db.in_transaction:
                db.rollback()
            db.close()
