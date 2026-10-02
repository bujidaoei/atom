"""The rollback bundle must capture real SQLite WAL content and every file."""
import importlib.util
import os
from pathlib import Path
import sqlite3
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "paired_backup.py"
spec = importlib.util.spec_from_file_location("paired_backup", SCRIPT)
paired = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = paired
spec.loader.exec_module(paired)
IMAGE = "sha256:" + "a" * 64


def _sources(tmp_path):
    data, broker, private = (tmp_path / name for name in ("data", "broker", "private"))
    for path in (data, broker, private):
        path.mkdir(mode=0o700)
    caddy = tmp_path / "Caddyfile"
    caddy.write_text("127.0.0.1 { respond ok }\n", encoding="utf-8")
    (data / "artifacts").mkdir()
    (data / "artifacts" / "saved.atomsnap").write_bytes(b"snapshot")
    (data / "published").mkdir()
    (data / "published" / "index.html").write_bytes(b"<html>old</html>")
    (broker / "registry.lease").write_bytes(b"lease")
    if os.name == "posix":
        (data / "current").symlink_to("published", target_is_directory=True)
    app = sqlite3.connect(data / "atom.db")
    app.execute("PRAGMA journal_mode=WAL")
    app.execute("PRAGMA user_version=10")
    app.execute("CREATE TABLE projects(id TEXT PRIMARY KEY)")
    app.execute("CREATE TABLE revision_records(id TEXT PRIMARY KEY)")
    app.execute("CREATE TABLE revision_artifacts(key TEXT PRIMARY KEY)")
    app.execute("INSERT INTO projects VALUES ('one')")
    app.commit()
    registry = sqlite3.connect(broker / "registry.db")
    registry.execute("PRAGMA user_version=3")
    registry.execute("CREATE TABLE attempts(id TEXT PRIMARY KEY)")
    registry.execute("INSERT INTO attempts VALUES ('one')")
    registry.commit()
    return data, broker, caddy, private, app, registry


def test_capture_verify_and_isolated_restore_with_live_wal(tmp_path):
    data, broker, caddy, private, app, registry = _sources(tmp_path)
    try:
        backup = private / "backup"
        receipt = paired.capture(data=data, broker=broker, caddy=caddy,
                                 destination=backup, image_id=IMAGE,
                                 app_schema=10, broker_schema=3)
        assert receipt["status"] == "verified"
        assert receipt["oldImageId"] == IMAGE
        assert receipt["counts"]["data"]["projects"] == 1
        assert receipt["counts"]["broker"]["attempts"] == 1
        assert not (backup / "data" / "atom.db-wal").exists()
        assert not (backup / "data" / "atom.db-shm").exists()
        if os.name == "posix":
            assert (backup / "data" / "current").is_symlink()
        restored = private / "restored"
        assert paired.restore(backup, restored) == receipt
        assert (restored / "data" / "published" / "index.html").read_bytes() == b"<html>old</html>"
        assert paired.verify(restored) == receipt
        (restored / "data" / "published" / "index.html").write_bytes(b"changed")
        with pytest.raises(paired.BackupError, match="backup_inventory_mismatch"):
            paired.verify(restored)
    finally:
        app.close()
        registry.close()


def test_capture_refuses_changed_source_without_success_receipt(tmp_path, monkeypatch):
    data, broker, caddy, private, app, registry = _sources(tmp_path)
    original = paired._sqlite_backup
    def changed(source, destination):
        original(source, destination)
        if source.name == "atom.db":
            (data / "artifacts" / "saved.atomsnap").write_bytes(b"changed")
    monkeypatch.setattr(paired, "_sqlite_backup", changed)
    try:
        backup = private / "changed"
        with pytest.raises(paired.BackupError, match="source_changed_during_backup"):
            paired.capture(data=data, broker=broker, caddy=caddy,
                           destination=backup, image_id=IMAGE,
                           app_schema=10, broker_schema=3)
        assert not (backup / "manifest.json").exists()
    finally:
        app.close()
        registry.close()


def test_capture_rejects_invalid_image_before_creating_backup(tmp_path):
    data, broker, caddy, private, app, registry = _sources(tmp_path)
    try:
        backup = private / "invalid"
        with pytest.raises(paired.BackupError, match="invalid_old_image"):
            paired.capture(data=data, broker=broker, caddy=caddy,
                           destination=backup, image_id="latest",
                           app_schema=10, broker_schema=3)
        assert not backup.exists()
    finally:
        app.close()
        registry.close()
