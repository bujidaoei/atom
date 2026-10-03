"""Capture, verify and restore a private application/broker/Caddy rollback pair.

Capture works while SQLite is in WAL mode, but the final cutover must stop
writers first. A manifest is written only after every copied file and both
SQLite backups pass verification. Restore always targets a new directory.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import sys
import time


IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
DATABASES = {"data": "atom.db", "broker": "registry.db"}
MAX_BACKUP_BYTES = 5 * 1024**3


class BackupError(RuntimeError):
    """Stable operator code; never includes user paths or file contents."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise BackupError(code)


def _absolute(path: Path) -> Path:
    _require(path.is_absolute() and ".." not in path.parts, "invalid_backup_path")
    return path


def _private_parent(path: Path) -> None:
    parent = path.parent
    _require(parent.is_dir() and not parent.is_symlink(), "missing_private_parent")
    if os.name == "posix":
        info = parent.stat()
        _require(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700,
                 "insecure_backup_parent")


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _entries(root: Path, *, omit_database: str | None = None) -> dict[str, dict]:
    """Inventory without following symlinks; reject devices and oversized sets."""
    entries: dict[str, dict] = {}
    total = 0

    def walk(directory: Path) -> None:
        nonlocal total
        for child in sorted(directory.iterdir()):
            if directory == root and omit_database is not None and child.name in {
                    omit_database, omit_database + "-wal", omit_database + "-shm",
                    omit_database + "-journal"}:
                continue
            relative = child.relative_to(root).as_posix()
            info = child.lstat()
            mode = stat.S_IMODE(info.st_mode)
            if stat.S_ISLNK(info.st_mode):
                entries[relative] = {"type": "symlink", "target": os.readlink(child)}
            elif stat.S_ISDIR(info.st_mode):
                entries[relative] = {"type": "directory", "mode": mode}
                walk(child)
            elif stat.S_ISREG(info.st_mode):
                total += info.st_size
                _require(total <= MAX_BACKUP_BYTES, "backup_size_limit")
                entries[relative] = {"type": "file", "mode": mode,
                                     "size": info.st_size, "sha256": _hash(child)}
            else:
                raise BackupError("unsupported_backup_entry")

    walk(root)
    return entries


def _database_summary(path: Path, expected_version: int) -> dict[str, int]:
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True,
                                     timeout=3)) as db:
            _require(db.execute("PRAGMA user_version").fetchone()[0] == expected_version,
                     "backup_schema_mismatch")
            _require(db.execute("PRAGMA integrity_check").fetchall() == [("ok",)],
                     "backup_integrity_failed")
            _require(db.execute("PRAGMA foreign_key_check").fetchall() == [],
                     "backup_foreign_key_failed")
            if expected_version in (10, 18):
                tables = ["projects", "revision_records", "revision_artifacts"]
                if expected_version == 18:
                    tables.extend(("release_records", "release_publications",
                                   "release_rollback_sources", "project_origin_ports"))
                return {name: db.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
                        for name in tables}
            if expected_version == 3:
                return {"attempts": db.execute("SELECT count(*) FROM attempts").fetchone()[0]}
            return {}
    except sqlite3.Error:
        raise BackupError("backup_database_unavailable") from None


def _sqlite_backup(source: Path, destination: Path) -> None:
    deadline = time.monotonic() + 30
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True,
                                     timeout=3)) as reader:
            with closing(sqlite3.connect(destination, timeout=3)) as writer:
                def progress(_status: int, _remaining: int, _total: int) -> None:
                    if time.monotonic() >= deadline:
                        raise BackupError("sqlite_backup_timeout")
                reader.backup(writer, pages=128, progress=progress, sleep=0.01)
                writer.execute("PRAGMA journal_mode=DELETE")
        destination.chmod(0o600)
        descriptor = os.open(destination, os.O_RDWR)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except sqlite3.Error:
        raise BackupError("sqlite_backup_failed") from None


def _manifest_bytes(manifest: dict) -> bytes:
    return (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _write_manifest(path: Path, manifest: dict) -> None:
    with path.open("xb") as output:
        output.write(_manifest_bytes(manifest))
        output.flush()
        os.fsync(output.fileno())
    path.chmod(0o600)
    if os.name == "posix":
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _safe_sources(data: Path, broker: Path, caddy: Path, destination: Path) -> None:
    _require(data != broker and data not in broker.parents and broker not in data.parents,
             "overlapping_backup_path")
    for source in (data, broker):
        _absolute(source)
        _require(source.is_dir() and not source.is_symlink(), "invalid_backup_source")
        _require(destination != source and destination not in source.parents
                 and source not in destination.parents, "overlapping_backup_path")
    _absolute(caddy)
    _require(caddy.is_file() and not caddy.is_symlink(), "invalid_caddy_source")
    _absolute(destination)
    _private_parent(destination)
    _require(not destination.exists() and not destination.is_symlink(),
             "backup_destination_exists")


def capture(*, data: Path, broker: Path, caddy: Path, destination: Path,
            image_id: str, app_schema: int, broker_schema: int) -> dict:
    """Make a consistent SQLite pair and byte-check every non-DB source file."""
    _safe_sources(data, broker, caddy, destination)
    _require(isinstance(image_id, str) and IMAGE.fullmatch(image_id) is not None,
             "invalid_old_image")
    _require(type(app_schema) is int and type(broker_schema) is int,
             "invalid_backup_schema")
    before = {"data": _database_summary(data / "atom.db", app_schema),
              "broker": _database_summary(broker / "registry.db", broker_schema)}
    source_files = {name: _entries(root, omit_database=DATABASES[name])
                    for name, root in (("data", data), ("broker", broker))}
    caddy_hash = _hash(caddy)
    destination.mkdir(mode=0o700)
    for name, root in (("data", data), ("broker", broker)):
        shutil.copytree(root, destination / name, symlinks=True,
                        ignore=lambda directory, names, database=DATABASES[name],
                                      source=root: ({database, database + "-wal",
                                                     database + "-shm", database + "-journal"}
                                                    & set(names))
                        if Path(directory) == source else set())
        _require(_entries(destination / name) == source_files[name],
                 "backup_copy_mismatch")
        _sqlite_backup(root / DATABASES[name], destination / name / DATABASES[name])
    shutil.copy2(caddy, destination / "Caddyfile", follow_symlinks=False)
    _require(_hash(caddy) == caddy_hash and
             _hash(destination / "Caddyfile") == caddy_hash,
             "caddy_changed_during_backup")
    _require({name: _entries(root, omit_database=DATABASES[name])
              for name, root in (("data", data), ("broker", broker))} == source_files,
             "source_changed_during_backup")
    after = {"data": _database_summary(data / "atom.db", app_schema),
             "broker": _database_summary(broker / "registry.db", broker_schema)}
    _require(after == before, "database_changed_during_backup")
    manifest = {"format": 1, "oldImageId": image_id,
                "schemas": {"data": app_schema, "broker": broker_schema},
                "counts": before,
                "entries": {name: _entries(destination / name)
                            for name in ("data", "broker")},
                "caddy": {"size": (destination / "Caddyfile").stat().st_size,
                          "sha256": caddy_hash}}
    for name in ("data", "broker"):
        _require(_database_summary(destination / name / DATABASES[name],
                                   manifest["schemas"][name]) == before[name],
                 "backup_database_mismatch")
    _write_manifest(destination / "manifest.json", manifest)
    return verify(destination)


def verify(directory: Path) -> dict:
    _absolute(directory)
    _require(directory.is_dir() and not directory.is_symlink(), "missing_backup")
    _require((directory / "manifest.json").is_file() and
             not (directory / "manifest.json").is_symlink(),
             "invalid_backup_manifest")
    try:
        manifest = json.loads((directory / "manifest.json").read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise BackupError("invalid_backup_manifest") from None
    _require(type(manifest) is dict and manifest.get("format") == 1 and
             type(manifest.get("entries")) is dict and
             set(manifest["entries"]) == {"data", "broker"} and
             type(manifest.get("schemas")) is dict and
             set(manifest["schemas"]) == {"data", "broker"} and
             type(manifest.get("counts")) is dict and
             set(manifest["counts"]) == {"data", "broker"} and
             type(manifest.get("caddy")) is dict and
             set(manifest["caddy"]) == {"size", "sha256"} and
             type(manifest["caddy"]["size"]) is int and
             type(manifest["caddy"]["sha256"]) is str and
             isinstance(manifest.get("oldImageId"), str) and
             IMAGE.fullmatch(manifest["oldImageId"]) is not None,
             "invalid_backup_manifest")
    _require(set(child.name for child in directory.iterdir()) ==
             {"data", "broker", "Caddyfile", "manifest.json"},
             "backup_inventory_mismatch")
    for name in ("data", "broker"):
        root = directory / name
        _require(root.is_dir() and not root.is_symlink() and
                 _entries(root) == manifest["entries"][name],
                 "backup_inventory_mismatch")
        _require(_database_summary(root / DATABASES[name],
                                   manifest["schemas"][name]) == manifest["counts"][name],
                 "backup_database_mismatch")
    caddy = directory / "Caddyfile"
    _require(caddy.is_file() and not caddy.is_symlink() and
             caddy.stat().st_size == manifest["caddy"]["size"] and
             _hash(caddy) == manifest["caddy"]["sha256"],
             "backup_caddy_mismatch")
    return {"status": "verified", "oldImageId": manifest["oldImageId"],
            "schemas": manifest["schemas"], "counts": manifest["counts"],
            "manifestSha256": _hash(directory / "manifest.json")}


def restore(source: Path, destination: Path) -> dict:
    """Prove that a complete pair can be reconstructed without touching live paths."""
    receipt = verify(source)
    _absolute(destination)
    _private_parent(destination)
    _require(destination != source and destination not in source.parents and
             source not in destination.parents and
             not destination.exists() and not destination.is_symlink(),
             "invalid_restore_destination")
    shutil.copytree(source, destination, symlinks=True)
    _require(verify(destination) == receipt, "restored_pair_mismatch")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture and verify an Atom rollback pair")
    subcommands = parser.add_subparsers(dest="command", required=True)
    capture_command = subcommands.add_parser("capture")
    for name in ("data", "broker", "caddy", "destination"):
        capture_command.add_argument("--" + name, type=Path, required=True)
    capture_command.add_argument("--image-id", required=True)
    capture_command.add_argument("--app-schema", type=int, required=True)
    capture_command.add_argument("--broker-schema", type=int, required=True)
    verify_command = subcommands.add_parser("verify")
    verify_command.add_argument("directory", type=Path)
    restore_command = subcommands.add_parser("restore")
    restore_command.add_argument("source", type=Path)
    restore_command.add_argument("destination", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "capture":
            result = capture(data=args.data, broker=args.broker, caddy=args.caddy,
                             destination=args.destination, image_id=args.image_id,
                             app_schema=args.app_schema, broker_schema=args.broker_schema)
        elif args.command == "verify":
            result = verify(args.directory)
        else:
            result = restore(args.source, args.destination)
    except (BackupError, OSError, shutil.Error) as error:
        code = str(error) if isinstance(error, BackupError) else "backup_io_failed"
        print(json.dumps({"error": code}), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
