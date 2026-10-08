"""The rollback bundle must capture real SQLite WAL content and every file."""
import os
from pathlib import Path
import sqlite3
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "paired_backup.py"
sys.path.insert(0, str(SCRIPT.parent))
import paired_backup as paired
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


def test_schema18_backup_retains_release_history_and_origin_inventory(tmp_path):
    data, broker, caddy, private, app, registry = _sources(tmp_path)
    try:
        app.execute("PRAGMA user_version=18")
        app.executescript("""
            CREATE TABLE release_records(id TEXT PRIMARY KEY, publication_generation INTEGER);
            CREATE TABLE release_publications(project_id TEXT PRIMARY KEY, release_id TEXT);
            CREATE TABLE release_rollback_sources(id TEXT PRIMARY KEY);
            CREATE TABLE project_origin_ports(project_id TEXT, purpose TEXT, port INTEGER);
            INSERT INTO release_records VALUES ('release-1', 1), ('release-2', 2);
            INSERT INTO release_publications VALUES ('one', 'release-2');
            INSERT INTO release_rollback_sources VALUES ('restore-2');
            INSERT INTO project_origin_ports VALUES ('one', 'preview', 20000),
                ('one', 'public', 20001);
        """)
        app.commit()
        backup = private / "schema18"
        receipt = paired.capture(data=data, broker=broker, caddy=caddy,
                                 destination=backup, image_id=IMAGE,
                                 app_schema=18, broker_schema=3)
        assert receipt["counts"]["data"] == {
            "projects": 1, "revision_records": 0, "revision_artifacts": 0,
            "release_records": 2, "release_publications": 1,
            "release_rollback_sources": 1, "project_origin_ports": 2}
        restored = private / "schema18-restored"
        assert paired.restore(backup, restored) == receipt
        with sqlite3.connect(restored / "data" / "atom.db") as db:
            assert db.execute("SELECT id FROM release_records "
                              "ORDER BY publication_generation").fetchall() == [
                                  ("release-1",), ("release-2",)]
            assert db.execute("SELECT release_id FROM release_publications").fetchone() == (
                "release-2",)
            assert db.execute("SELECT purpose,port FROM project_origin_ports "
                              "ORDER BY port").fetchall() == [
                                  ("preview", 20000), ("public", 20001)]
    finally:
        app.close()
        registry.close()
