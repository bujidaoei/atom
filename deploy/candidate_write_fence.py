"""Read-only logical fingerprint for a quiesced publication candidate.

This is evidence for the operational rollback gate, not an authorization to
replace a live database. The caller must exclude writers across its final
comparison and container handoff.
"""

from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat

import paired_backup


class FenceError(RuntimeError):
    """Stable operator error without paths or user content."""


def _feed(digest: object, value: object) -> None:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    digest.update(len(payload).to_bytes(8, "big"))
    digest.update(payload)


def _value(value: object) -> list[object]:
    if value is None:
        return ["null"]
    if type(value) is int:
        return ["integer", value]
    if type(value) is float:
        return ["real", repr(value)]
    if type(value) is str:
        return ["text", value]
    if type(value) is bytes:
        return ["blob", value.hex()]
    raise FenceError("unsupported_database_value")


def _quoted(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def database_fingerprint(path: Path) -> str:
    """Hash schema and typed rows, ignoring SQLite page/WAL layout."""
    if not path.is_absolute() or path.is_symlink():
        raise FenceError("invalid_candidate_database")
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise FenceError("invalid_candidate_database")
        digest = hashlib.sha256()
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True,
                                     timeout=5)) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            schema = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master "
                                "ORDER BY type,name,tbl_name").fetchall()
            _feed(digest, ["schema", [[_value(cell) for cell in row]
                                       for row in schema]])
            for kind, name, _table, _sql in schema:
                if kind != "table" or (name.startswith("sqlite_")
                                       and name != "sqlite_sequence"):
                    continue
                columns = db.execute("PRAGMA table_info(" + _quoted(name) + ")").fetchall()
                _feed(digest, ["table", name, [[_value(cell) for cell in column]
                                                for column in columns]])
                try:
                    rows = db.execute("SELECT * FROM " + _quoted(name) + " ORDER BY rowid")
                except sqlite3.OperationalError:
                    ordering = ",".join(str(index) for index in range(1, len(columns) + 1))
                    rows = db.execute("SELECT * FROM " + _quoted(name) + " ORDER BY "
                                      + ordering)
                for row in rows:
                    _feed(digest, [_value(cell) for cell in row])
            db.execute("ROLLBACK")
        return digest.hexdigest()
    except (OSError, sqlite3.Error) as exc:
        raise FenceError("candidate_database_unavailable") from exc


def state_fingerprint(data_directory: Path) -> str:
    """Hash the application ledger and every non-SQLite file without following links."""
    if not data_directory.is_absolute() or data_directory.is_symlink():
        raise FenceError("invalid_candidate_data")
    try:
        if not data_directory.is_dir():
            raise FenceError("invalid_candidate_data")
        database = database_fingerprint(data_directory / "atom.db")
        files = paired_backup._entries(data_directory, omit_database="atom.db")
        if any(item["type"] == "symlink" for item in files.values()):
            raise FenceError("candidate_symlink_present")
        digest = hashlib.sha256()
        _feed(digest, ["database", database])
        _feed(digest, ["files", files])
        return digest.hexdigest()
    except (OSError, paired_backup.BackupError) as exc:
        raise FenceError("candidate_files_unavailable") from exc


def candidate_fingerprint(candidate_directory: Path) -> str:
    """Cover both application data and broker records; ignore the process lease."""
    if not candidate_directory.is_absolute() or candidate_directory.is_symlink():
        raise FenceError("invalid_candidate_directory")
    broker = candidate_directory / "broker"
    try:
        if broker.is_symlink() or not broker.is_dir():
            raise FenceError("invalid_candidate_broker")
        broker_files = paired_backup._entries(broker, omit_database="registry.db")
        if any(item["type"] == "symlink" for item in broker_files.values()):
            raise FenceError("candidate_symlink_present")
        broker_files.pop("registry.lease", None)
        digest = hashlib.sha256()
        _feed(digest, ["app", state_fingerprint(candidate_directory / "data")])
        _feed(digest, ["broker", database_fingerprint(broker / "registry.db")])
        _feed(digest, ["brokerFiles", broker_files])
        return digest.hexdigest()
    except (OSError, paired_backup.BackupError) as exc:
        raise FenceError("candidate_files_unavailable") from exc


def capture_baseline(path: Path, *, candidate_directory: Path, revision: str,
                     candidate_image: str) -> str:
    """Seal the pre-ingress candidate state in the root-private cutover ledger."""
    if (not path.is_absolute() or not candidate_directory.is_absolute()
            or path.exists() or path.is_symlink()):
        raise FenceError("invalid_baseline_path")
    parent = path.parent.stat()
    if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0
            or stat.S_IMODE(parent.st_mode) != 0o700):
        raise FenceError("insecure_baseline_directory")
    digest = candidate_fingerprint(candidate_directory)
    record = {"schemaVersion": 1, "revision": revision,
              "candidateImageId": candidate_image,
              "candidateDirectory": str(candidate_directory), "stateSha256": digest}
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(record, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, type=Path)
    arguments = parser.parse_args(argv)
    try:
        digest = state_fingerprint(arguments.data)
    except FenceError as exc:
        parser.exit(2, str(exc) + "\n")
    print(json.dumps({"candidateStateSha256": digest}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
