"""Read-only production pair preflight with a durable, root-private receipt.

The cutover transaction itself is intentionally not exposed until its rollback
and crash gates are implemented. This command is safe to run before a release:
it checks the exact source/image and live pair, then records an atomic result.
"""

from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
try:
    import fcntl
except ImportError:  # Local parser tests also run on Windows; deployment is Linux-only.
    fcntl = None
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import sys
from urllib.parse import quote


REVISION = re.compile(r"[0-9a-f]{40}\Z")
IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
CONTAINER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,80}\Z")
NETWORK = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,80}\Z")
CONFIG_KEYS = frozenset({
    "schemaVersion", "apiContainer", "brokerContainer", "dataDirectory",
    "brokerDataDirectory", "backupRoot", "stateDirectory", "network",
    "loopbackPort", "applicationSchema", "brokerSchema", "dockerBinary",
    "dockerSocket",
})
FINAL_OUTCOMES = frozenset({"completed", "rolled_back", "needs_operator"})


class CutoverError(RuntimeError):
    """Stable operator code; never embeds inspected environment values."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise CutoverError(code)


def _absolute(value: object, code: str) -> Path:
    _require(type(value) is str and bool(value), code)
    path = Path(value)
    _require(path.is_absolute() and ".." not in path.parts, code)
    return path


def _trusted_parents(path: Path) -> None:
    for parent in path.parents:
        info = parent.lstat()
        mode = info.st_mode
        _require(stat.S_ISDIR(mode) and info.st_uid == 0 and
                 (mode & 0o022 == 0 or mode & stat.S_ISVTX != 0),
                 "insecure_parent_directory")


@dataclass(frozen=True)
class CutoverConfig:
    api: str
    broker: str
    data: Path
    broker_data: Path
    backup_root: Path
    state_dir: Path
    network: str
    loopback_port: int
    app_schema: int
    broker_schema: int
    docker: Path
    docker_socket: Path

    @classmethod
    def parse(cls, raw: object) -> "CutoverConfig":
        _require(type(raw) is dict and set(raw) == CONFIG_KEYS, "invalid_config_fields")
        _require(type(raw["schemaVersion"]) is int and raw["schemaVersion"] == 1,
                 "invalid_config_version")
        api, broker, network = raw["apiContainer"], raw["brokerContainer"], raw["network"]
        _require(type(api) is str and CONTAINER.fullmatch(api) is not None,
                 "invalid_api_container")
        _require(type(broker) is str and CONTAINER.fullmatch(broker) is not None
                 and broker != api, "invalid_broker_container")
        _require(type(network) is str and NETWORK.fullmatch(network) is not None,
                 "invalid_network")
        port = raw["loopbackPort"]
        _require(type(port) is int and 1024 <= port <= 65535, "invalid_loopback_port")
        app_schema, broker_schema = raw["applicationSchema"], raw["brokerSchema"]
        _require(type(app_schema) is int and 1 <= app_schema <= 1000 and
                 type(broker_schema) is int and 1 <= broker_schema <= 1000,
                 "invalid_expected_schema")
        data = _absolute(raw["dataDirectory"], "invalid_data_directory")
        broker_data = _absolute(raw["brokerDataDirectory"], "invalid_broker_directory")
        backup_root = _absolute(raw["backupRoot"], "invalid_backup_root")
        state_dir = _absolute(raw["stateDirectory"], "invalid_state_directory")
        docker = _absolute(raw["dockerBinary"], "invalid_docker_binary")
        docker_socket = _absolute(raw["dockerSocket"], "invalid_docker_socket")
        roots = (data, broker_data, backup_root, state_dir)
        _require(all(left != right and left not in right.parents and right not in left.parents
                     for index, left in enumerate(roots) for right in roots[index + 1:]),
                 "overlapping_cutover_directories")
        return cls(api, broker, data, broker_data, backup_root, state_dir,
                   network, port, app_schema, broker_schema, docker, docker_socket)


def load_config(path: Path) -> CutoverConfig:
    try:
        _trusted_parents(path)
        info = path.lstat()
        _require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and
                 stat.S_IMODE(info.st_mode) == 0o600, "insecure_config_file")
        return CutoverConfig.parse(json.loads(path.read_text("utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CutoverError("unreadable_config_file") from error


def _command(args: list[str], *, timeout: int = 15) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CutoverError("preflight_command_unavailable") from error
    _require(result.returncode == 0, "preflight_command_failed")
    return result.stdout.strip()


def _inspect(docker: Path, kind: str, target: str) -> dict:
    raw = _command([str(docker), kind, "inspect", target])
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError as error:
        raise CutoverError("invalid_docker_inspect") from error
    _require(type(rows) is list and len(rows) == 1 and type(rows[0]) is dict,
             "invalid_docker_inspect")
    return rows[0]


def _database(path: Path, expected_version: int, *, broker: bool) -> None:
    _require(path.is_file() and not path.is_symlink(), "missing_database")
    try:
        uri = "file:" + quote(str(path), safe="/") + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=3)) as db:
            _require(db.execute("PRAGMA user_version").fetchone()[0] == expected_version,
                     "schema_mismatch")
            _require(db.execute("PRAGMA quick_check").fetchall() == [("ok",)],
                     "database_integrity_failed")
            _require(db.execute("PRAGMA foreign_key_check").fetchall() == [],
                     "database_foreign_key_failed")
            if broker:
                _require(db.execute("SELECT count(*) FROM attempts WHERE state != 'terminated'")
                         .fetchone()[0] == 0, "live_broker_attempt")
            else:
                _require(db.execute("SELECT count(*) FROM projects WHERE active_run_id IS NOT NULL")
                         .fetchone()[0] == 0, "active_project")
                _require(db.execute("SELECT count(*) FROM revision_attempts WHERE state != 'closed'")
                         .fetchone()[0] == 0, "open_revision_attempt")
    except sqlite3.Error as error:
        raise CutoverError("database_unavailable") from error


def _expected_binds(config: CutoverConfig) -> tuple[set[str], set[str]]:
    return ({f"{config.data}:/data"},
            {f"{config.broker_data}:/broker",
             f"{config.docker_socket}:{config.docker_socket}",
             f"{config.docker}:{config.docker}:ro"})


def preflight(config: CutoverConfig, *, source: Path, revision: str,
              image_id: str) -> dict[str, object]:
    _require(REVISION.fullmatch(revision) is not None and
             IMAGE.fullmatch(image_id) is not None, "invalid_release_identity")
    _require(source.is_absolute() and source.is_dir() and not source.is_symlink(),
             "invalid_source_checkout")
    _require(all(source != root and source not in root.parents and root not in source.parents
                 for root in (config.data, config.broker_data, config.backup_root,
                              config.state_dir)), "overlapping_source_checkout")
    _require(config.data.is_dir() and config.broker_data.is_dir() and
             config.backup_root.is_dir(), "missing_cutover_directory")
    _require(config.backup_root.stat().st_uid == 0 and
             stat.S_IMODE(config.backup_root.stat().st_mode) == 0o700,
             "insecure_backup_root")
    _trusted_parents(config.backup_root)
    _require(config.docker.is_file() and config.docker_socket.exists(),
             "missing_docker_access")
    _require(_command(["git", "-c", f"safe.directory={source}", "-C", str(source),
                       "rev-parse", "HEAD"]) == revision, "source_revision_mismatch")
    _require(_command(["git", "-c", f"safe.directory={source}", "-C", str(source),
                       "status", "--porcelain"]) == "", "source_not_clean")
    image = _inspect(config.docker, "image", image_id)
    _require(image.get("Id") == image_id and
             image.get("Config", {}).get("Labels", {}).get("atom.revision") == revision,
             "image_revision_mismatch")
    api = _inspect(config.docker, "container", config.api)
    broker = _inspect(config.docker, "container", config.broker)
    for item in (api, broker):
        _require(item.get("State", {}).get("Running") is True and
                 item.get("State", {}).get("Health", {}).get("Status") == "healthy",
                 "old_pair_unhealthy")
    _require(api.get("Image") == broker.get("Image"), "old_pair_image_mismatch")
    api_host = api.get("HostConfig", {})
    broker_host = broker.get("HostConfig", {})
    api_binds, broker_binds = _expected_binds(config)
    _require(api_host.get("NetworkMode") == config.network and
             set(api_host.get("Binds") or ()) == api_binds and
             api_host.get("PortBindings") == {"80/tcp": [{"HostIp": "127.0.0.1",
                                                        "HostPort": str(config.loopback_port)}]} and
             api_host.get("RestartPolicy", {}).get("Name") == "unless-stopped" and
             api_host.get("Privileged") is False,
             "api_profile_mismatch")
    _require(broker_host.get("NetworkMode") == "container:" + api["Id"] and
             set(broker_host.get("Binds") or ()) == broker_binds and
             broker_host.get("ReadonlyRootfs") is True and
             broker_host.get("Tmpfs") == {"/tmp": "size=32m"} and
             broker_host.get("SecurityOpt") == ["no-new-privileges"] and
             broker_host.get("RestartPolicy", {}).get("Name") == "unless-stopped" and
             broker_host.get("Privileged") is False and
             broker.get("Config", {}).get("Cmd") ==
             ["/app/backend/.venv/bin/python", "-m", "app.sandbox"],
             "broker_profile_mismatch")
    _require([row for row in broker.get("Config", {}).get("Env", [])
              if row.startswith("ATOM_BROKER_IMAGE=")] ==
             ["ATOM_BROKER_IMAGE=" + api["Image"]], "broker_image_mismatch")
    _database(config.data / "atom.db", config.app_schema, broker=False)
    _database(config.broker_data / "registry.db", config.broker_schema, broker=True)
    backup = config.backup_root / ("pre-" + revision[:12])
    _require(not backup.exists(), "backup_already_exists")
    return {"oldImageId": api["Image"], "backupDirectory": str(backup)}


def _root_private(path: Path, *, create: bool = False) -> None:
    try:
        _trusted_parents(path)
    except OSError as error:
        raise CutoverError("missing_state_parent") from error
    if create and not path.exists():
        path.mkdir(mode=0o700, parents=True)
    try:
        info = path.lstat()
    except OSError as error:
        raise CutoverError("missing_state_directory") from error
    _require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and
             stat.S_IMODE(info.st_mode) == 0o700, "insecure_state_directory")


class PhaseLedger:
    def __init__(self, directory: Path, revision: str):
        _require(REVISION.fullmatch(revision) is not None, "invalid_release_identity")
        self.directory = directory
        self.path = directory / (revision + ".json")

    def read(self) -> dict[str, object] | None:
        _root_private(self.directory)
        if not self.path.exists():
            return None
        info = self.path.lstat()
        _require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and
                 stat.S_IMODE(info.st_mode) == 0o600, "insecure_status_file")
        try:
            record = json.loads(self.path.read_text("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise CutoverError("invalid_status_file") from error
        _require(type(record) is dict and record.get("revision") == self.path.stem,
                 "invalid_status_file")
        return record

    def write(self, *, outcome: str, image_id: str, details: dict[str, object]) -> None:
        _require(not (set(details) & {"schemaVersion", "revision", "imageId",
                                       "outcome", "updatedAt"}),
                 "invalid_status_details")
        _root_private(self.directory, create=True)
        previous = self.read()
        _require(previous is None or previous.get("outcome") not in FINAL_OUTCOMES,
                 "terminal_status_exists")
        _require(previous is None or previous.get("imageId") == image_id,
                 "status_image_mismatch")
        record = {"schemaVersion": 1, "revision": self.path.stem,
                  "imageId": image_id, "outcome": outcome,
                  "updatedAt": datetime.now(timezone.utc).isoformat(), **details}
        payload = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
        temporary = self.directory / (self.path.name + ".new-" + os.urandom(8).hex())
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            directory = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)


@contextmanager
def host_lock():
    _require(fcntl is not None, "linux_required")
    path = Path("/run/atom-protected-cutover.lock")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                         0o600)
    try:
        info = os.fstat(descriptor)
        _require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and
                 stat.S_IMODE(info.st_mode) == 0o600, "insecure_cutover_lock")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise CutoverError("cutover_lock_busy") from error
        yield
    finally:
        os.close(descriptor)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preflight", "status"))
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--image-id")
    args = parser.parse_args(argv)
    try:
        _require(getattr(os, "geteuid", lambda: -1)() == 0, "root_required")
        config = load_config(args.config)
        ledger = PhaseLedger(config.state_dir, args.revision)
        if args.mode == "status":
            record = ledger.read()
            _require(record is not None, "status_not_found")
            print(json.dumps(record, sort_keys=True))
            return 0
        _require(args.source is not None and args.image_id is not None,
                 "missing_release_identity")
        with host_lock():
            try:
                details = preflight(config, source=args.source,
                                    revision=args.revision, image_id=args.image_id)
            except CutoverError as error:
                if IMAGE.fullmatch(args.image_id) is not None:
                    ledger.write(outcome="preflight_rejected", image_id=args.image_id,
                                 details={"reason": str(error)})
                raise
            ledger.write(outcome="preflight_passed", image_id=args.image_id,
                         details=details)
        print(json.dumps(ledger.read(), sort_keys=True))
        return 0
    except CutoverError as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
