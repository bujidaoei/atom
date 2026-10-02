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


@dataclass(frozen=True)
class BackupResult:
    version: int
    sha256: str


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
    if version not in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18):
        raise MigrationError("unsupported_schema")
    expected = SCHEMA
    hashes = [(1, MIGRATION_HASH)]
    if version >= 2:
        from . import release_v2
        expected = {**SCHEMA, **release_v2.SCHEMA}
        hashes.append((2, release_v2.MIGRATION_HASH))
    if version >= 3:
        from . import content_v3
        expected = {**expected, **content_v3.SCHEMA}
        hashes.append((3, content_v3.MIGRATION_HASH))
    if version >= 4:
        from . import access_v4
        expected = {**expected, **access_v4.SCHEMA}
        hashes.append((4, access_v4.MIGRATION_HASH))
    if version >= 5:
        from . import audit_v5
        expected = {**expected, **audit_v5.SCHEMA}
        hashes.append((5, audit_v5.MIGRATION_HASH))
    if version >= 6:
        from . import audit_governance_v6
        expected = {**expected, **audit_governance_v6.SCHEMA}
        hashes.append((6, audit_governance_v6.MIGRATION_HASH))
    if version >= 7:
        from . import audit_commands_v7
        expected = {**expected, **audit_commands_v7.SCHEMA}
        hashes.append((7, audit_commands_v7.MIGRATION_HASH))
    if version >= 8:
        from . import audit_retention_v8
        expected = {**expected, **audit_retention_v8.SCHEMA}
        hashes.append((8, audit_retention_v8.MIGRATION_HASH))
    if version >= 9:
        from . import audit_archives_v9
        expected = {**expected, **audit_archives_v9.SCHEMA}
        hashes.append((9, audit_archives_v9.MIGRATION_HASH))
    if version >= 10:
        from . import audit_recovery_v10
        expected = {**expected, **audit_recovery_v10.SCHEMA}
        hashes.append((10, audit_recovery_v10.MIGRATION_HASH))
    if version >= 11:
        from . import audit_pruning_v11
        expected = {**expected, **audit_pruning_v11.SCHEMA}
        hashes.append((11, audit_pruning_v11.MIGRATION_HASH))
    if version >= 12:
        from . import adoption_v12
        expected = {**expected, **adoption_v12.SCHEMA}
        hashes.append((12, adoption_v12.MIGRATION_HASH))
    if version >= 13:
        from . import verifier_v13
        expected = {**expected, **verifier_v13.SCHEMA}
        hashes.append((13, verifier_v13.MIGRATION_HASH))
    if version >= 14:
        from . import rollback_v14
        expected = {**expected, **rollback_v14.SCHEMA}
        hashes.append((14, rollback_v14.MIGRATION_HASH))
    if version >= 15:
        from . import verification_index_v15
        expected = {**expected, **verification_index_v15.SCHEMA}
        hashes.append((15, verification_index_v15.MIGRATION_HASH))
    if version >= 16:
        from . import publication_policy_v16
        expected = {**expected, **publication_policy_v16.SCHEMA}
        hashes.append((16, publication_policy_v16.MIGRATION_HASH))
    if version >= 17:
        from . import project_origins_v17
        expected = {**expected, **project_origins_v17.SCHEMA}
        hashes.append((17, project_origins_v17.MIGRATION_HASH))
    if version >= 18:
        from . import preview_access_v18
        expected = {**expected, **preview_access_v18.SCHEMA}
        hashes.append((18, preview_access_v18.MIGRATION_HASH))
    rows = db.execute("SELECT type,name,sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' AND sql IS NOT NULL ORDER BY type,name").fetchall()
    extension = {name: sql for kind, name, sql in rows if name in expected}
    baseline = [(kind, name, sql) for kind, name, sql in rows if name not in expected]
    digest = hashlib.sha256(json.dumps(baseline, separators=(",", ":")).encode()).hexdigest()
    if digest != BASELINE_HASH or (version == 0 and extension):
        raise MigrationError("unsupported_schema")
    if version:
        if extension != expected:
            raise MigrationError("unsupported_schema")
        journal = db.execute("SELECT version,migration_hash FROM atom_schema_migrations ORDER BY version").fetchall()
        if journal != hashes:
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


def verify_backup(path: Path, *, expected_version: int = 0) -> str:
    if type(expected_version) is not int or expected_version not in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18):
        raise MigrationError("invalid_backup_version")
    db = None
    try:
        path = _path(path, existing=True)
        db = _open(path, readonly=True)
        if _schema(db) != expected_version:
            raise MigrationError("invalid_backup_version")
        _integrity(db)
        return _digest(path)
    except (OSError, sqlite3.Error):
        raise MigrationError("backup_unavailable") from None
    finally:
        if db is not None:
            db.close()


def _backup(source, destination, *, expected_version=0):
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
        if _schema(target) != expected_version:
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
    return verify_backup(destination, expected_version=expected_version)


def backup_database(path: Path, backup: Path, *, lock_timeout: float = 3) -> BackupResult:
    """Snapshot a supported database under writer exclusion; never overwrite.

    Operators must still stop application writers and protect parent paths.
    The returned version is the exact schema verified in the saved snapshot.
    """
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
        digest = _backup(path, backup, expected_version=version)
        return BackupResult(version, digest)
    except (OSError, sqlite3.Error):
        raise MigrationError("backup_unavailable") from None
    finally:
        if db is not None:
            if db.in_transaction:
                db.rollback()
            db.close()


def migrate(path: Path, backup: Path, *, lock_timeout: float = 3, target_version: int = 1) -> MigrationResult:
    if type(target_version) is not int or target_version not in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18):
        raise MigrationError("invalid_target_version")
    if isinstance(lock_timeout, bool) or not isinstance(lock_timeout, (int, float)) or not 0 < lock_timeout <= 10:
        raise MigrationError("invalid_migration_timeout")
    db = None
    try:
        path, backup = _path(path, existing=True), _path(backup, existing=False)
        if path.resolve() == backup.resolve():
            raise MigrationError("invalid_backup_path")
        db = _open(path, timeout=lock_timeout)
        if target_version in (12, 16):
            # SQLite requires this outside a transaction for a table rebuild.
            if _schema(db) not in (target_version - 1, target_version):
                raise MigrationError(f"migration_requires_v{target_version - 1}")
            db.execute("PRAGMA foreign_keys=OFF")
            if db.execute("PRAGMA foreign_keys").fetchone() != (0,):
                raise MigrationError("migration_failed")
        if target_version == 13 and _schema(db) not in (12, 13):
            raise MigrationError("migration_requires_v12")
        if target_version == 14 and _schema(db) not in (13, 14):
            raise MigrationError("migration_requires_v13")
        if target_version == 15 and _schema(db) not in (14, 15):
            raise MigrationError("migration_requires_v14")
        db.execute("BEGIN IMMEDIATE")
        version = _schema(db)
        _integrity(db)
        if target_version == 12 and version not in (11, 12):
            raise MigrationError(f"migration_requires_v{target_version - 1}")
        if target_version == 13 and version not in (12, 13):
            raise MigrationError("migration_requires_v12")
        if target_version == 14 and version not in (13, 14):
            raise MigrationError("migration_requires_v13")
        if target_version == 16 and version not in (15, 16):
            raise MigrationError("migration_requires_v15")
        if target_version == 17 and version not in (16, 17):
            raise MigrationError("migration_requires_v16")
        if target_version == 18 and version not in (17, 18):
            raise MigrationError("migration_requires_v17")
        if target_version == 15 and version not in (14, 15):
            raise MigrationError("migration_requires_v14")
        if version > target_version:
            raise MigrationError("migration_downgrade_denied")
        if version == target_version:
            digest = db.execute("SELECT backup_sha256 FROM atom_schema_migrations WHERE version=?", (version,)).fetchone()[0]
            db.execute("ROLLBACK")
            return MigrationResult(version, False, digest)
        digest = _backup(path, backup, expected_version=version)
        if version == 0:
            _apply_revision_schema(db)
            db.execute("INSERT INTO atom_schema_migrations VALUES (1,?,?,?)", (MIGRATION_HASH, digest, int(time.time())))
        if version < 2 <= target_version:
            from . import release_v2
            release_v2.apply(db)
            db.execute("INSERT INTO atom_schema_migrations VALUES (2,?,?,?)", (release_v2.MIGRATION_HASH, digest, int(time.time())))
        if version < 3 <= target_version:
            from . import content_v3
            content_v3.apply(db)
            db.execute("INSERT INTO atom_schema_migrations VALUES (3,?,?,?)", (content_v3.MIGRATION_HASH, digest, int(time.time())))
        if version < 4 <= target_version:
            from . import access_v4
            access_v4.apply(db)
            db.execute("INSERT INTO atom_schema_migrations VALUES (4,?,?,?)", (access_v4.MIGRATION_HASH, digest, int(time.time())))
        if version < 5 <= target_version:
            from . import audit_v5
            audit_v5.apply(db)
            db.execute("INSERT INTO atom_schema_migrations VALUES (5,?,?,?)", (audit_v5.MIGRATION_HASH, digest, int(time.time())))
        if version < 6 <= target_version:
            from . import audit_governance_v6
            audit_governance_v6.apply(db)
            db.execute("INSERT INTO atom_schema_migrations VALUES (6,?,?,?)", (audit_governance_v6.MIGRATION_HASH, digest, int(time.time())))
        if version < 7 <= target_version:
            from . import audit_commands_v7
            audit_commands_v7.apply(db)
            db.execute("INSERT INTO atom_schema_migrations VALUES (7,?,?,?)", (audit_commands_v7.MIGRATION_HASH, digest, int(time.time())))
        if version < 8 <= target_version:
            from . import audit_retention_v8
            audit_retention_v8.apply(db)
            db.execute("INSERT INTO atom_schema_migrations VALUES (8,?,?,?)", (audit_retention_v8.MIGRATION_HASH, digest, int(time.time())))
        if version < 9 <= target_version:
            from . import audit_archives_v9
            audit_archives_v9.apply(db)
            db.execute("INSERT INTO atom_schema_migrations VALUES (9,?,?,?)", (audit_archives_v9.MIGRATION_HASH, digest, int(time.time())))
        if version < 10 <= target_version:
            from . import audit_recovery_v10
            audit_recovery_v10.apply(db)
            db.execute("INSERT INTO atom_schema_migrations VALUES (10,?,?,?)", (audit_recovery_v10.MIGRATION_HASH, digest, int(time.time())))
        if version < 11 <= target_version:
            from . import audit_pruning_v11
            audit_pruning_v11.apply(db)
            db.execute("INSERT INTO atom_schema_migrations VALUES (11,?,?,?)", (audit_pruning_v11.MIGRATION_HASH, digest, int(time.time())))
        if version < 12 <= target_version:
            from . import adoption_v12
            adoption_v12.apply(db)
            db.execute("INSERT INTO atom_schema_migrations VALUES (12,?,?,?)", (adoption_v12.MIGRATION_HASH, digest, int(time.time())))
        if version < 13 <= target_version:
            from . import verifier_v13
            verifier_v13.apply(db)
            db.execute("INSERT INTO atom_schema_migrations VALUES (13,?,?,?)", (verifier_v13.MIGRATION_HASH, digest, int(time.time())))
        if version < 14 <= target_version:
            from . import rollback_v14
            rollback_v14.apply(db)
            db.execute("INSERT INTO atom_schema_migrations VALUES (14,?,?,?)", (rollback_v14.MIGRATION_HASH, digest, int(time.time())))
        if version < 15 <= target_version:
            from . import verification_index_v15
            verification_index_v15.apply(db)
            db.execute("INSERT INTO atom_schema_migrations VALUES (15,?,?,?)", (verification_index_v15.MIGRATION_HASH, digest, int(time.time())))
        if version < 16 <= target_version:
            from . import publication_policy_v16
            publication_policy_v16.apply(db)
            db.execute("INSERT INTO atom_schema_migrations VALUES (16,?,?,?)", (publication_policy_v16.MIGRATION_HASH, digest, int(time.time())))
        if version < 17 <= target_version:
            from . import project_origins_v17
            project_origins_v17.apply(db)
            db.execute("INSERT INTO atom_schema_migrations VALUES (17,?,?,?)", (project_origins_v17.MIGRATION_HASH, digest, int(time.time())))
        if version < 18 <= target_version:
            from . import preview_access_v18
            preview_access_v18.apply(db)
            db.execute("INSERT INTO atom_schema_migrations VALUES (18,?,?,?)", (preview_access_v18.MIGRATION_HASH, digest, int(time.time())))
        db.execute(f"PRAGMA user_version={target_version}")
        _schema(db)
        _integrity(db)
        db.execute("COMMIT")
        return MigrationResult(target_version, True, digest)
    except (OSError, sqlite3.Error):
        raise MigrationError("migration_failed") from None
    finally:
        if db is not None:
            if db.in_transaction:
                db.rollback()
            db.close()
