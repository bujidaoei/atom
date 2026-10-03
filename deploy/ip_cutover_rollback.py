"""Restore the preserved old container pair after a failed IP publication cutover.

The old containers and schema-10 data are never rebuilt or migrated in place.
This command uses recorded Docker IDs, not names alone, before it removes a
candidate or starts the old pair. The new data directory remains for diagnosis.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener
from urllib.parse import urlsplit
import ssl
from ipaddress import ip_address

from protected_cutover import CutoverError, PhaseLedger, host_lock


IDENTITY = re.compile(r"[0-9a-f]{64}\Z")
IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,80}\Z")
CONTAINERS = {
    "api": "atom-candidate", "broker": "atom-candidate-broker", "caddy": "atom-tls",
}
ROLLBACK_NAMES = {key: value + "-rollback" for key, value in CONTAINERS.items()}
EXTRA = {"atom-preview": "atom-ip-publication", "atom-public": "atom-ip-publication",
         "atom-verifier": "atom-ip-verifier"}


class RollbackError(RuntimeError):
    """Stable non-secret code suitable for a phase receipt."""


def _run(*args: str, timeout: int = 120, allow_missing: bool = False) -> str | None:
    try:
        result = subprocess.run(["docker", *args], capture_output=True, text=True,
                                timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RollbackError("docker_unavailable") from exc
    if result.returncode:
        if allow_missing and "No such container" in result.stderr:
            return None
        raise RollbackError("docker_command_failed")
    return result.stdout.strip()


def _inspect(name: str) -> dict | None:
    raw = _run("container", "inspect", name, timeout=15, allow_missing=True)
    if raw is None:
        return None
    try:
        rows = json.loads(raw)
    except ValueError as exc:
        raise RollbackError("invalid_container_inspection") from exc
    if type(rows) is not list or len(rows) != 1 or type(rows[0]) is not dict:
        raise RollbackError("invalid_container_inspection")
    return rows[0]


def _identity(path: Path) -> dict:
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
            or stat.S_IMODE(info.st_mode) != 0o600):
        raise RollbackError("insecure_rollback_identity")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise RollbackError("invalid_rollback_identity") from exc
    if (type(record) is not dict or set(record) != {
            "schemaVersion", "revision", "oldImageId", "candidateImageId",
            "containers", "stateDirectory"} or record["schemaVersion"] != 1
            or not isinstance(record["revision"], str)
            or re.fullmatch(r"[0-9a-f]{40}", record["revision"]) is None
            or any(not isinstance(record[key], str) or IMAGE.fullmatch(record[key]) is None
                   for key in ("oldImageId", "candidateImageId"))
            or type(record["containers"]) is not dict
            or set(record["containers"]) != set(CONTAINERS)
            or any(not isinstance(value, str) or IDENTITY.fullmatch(value) is None
                   for value in record["containers"].values())
            or not isinstance(record["stateDirectory"], str)
            or not Path(record["stateDirectory"]).is_absolute()):
        raise RollbackError("invalid_rollback_identity")
    return record


def capture_identity(path: Path, *, revision: str, candidate_image: str) -> dict:
    """Persist the current old IDs before a writer is stopped or renamed."""
    if (not path.is_absolute() or not isinstance(revision, str)
            or re.fullmatch(r"[0-9a-f]{40}", revision) is None
            or not isinstance(candidate_image, str)
            or IMAGE.fullmatch(candidate_image) is None):
        raise RollbackError("invalid_identity_capture")
    parent = path.parent
    info = parent.stat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise RollbackError("insecure_identity_directory")
    containers = {}
    old_image = None
    for role, name in CONTAINERS.items():
        item = _inspect(name)
        if (item is None or item.get("State", {}).get("Running") is not True
                or not isinstance(item.get("Id"), str)
                or IDENTITY.fullmatch(item["Id"]) is None
                or _inspect(ROLLBACK_NAMES[role]) is not None):
            raise RollbackError("old_container_not_ready")
        if role != "caddy":
            if old_image is None:
                old_image = item.get("Image")
            elif old_image != item.get("Image"):
                raise RollbackError("old_pair_image_mismatch")
        containers[role] = item["Id"]
    if (not isinstance(old_image, str) or IMAGE.fullmatch(old_image) is None
            or old_image == candidate_image or any(_inspect(name) is not None for name in EXTRA)):
        raise RollbackError("candidate_not_isolated")
    record = {"schemaVersion": 1, "revision": revision, "oldImageId": old_image,
              "candidateImageId": candidate_image, "containers": containers,
              "stateDirectory": str(parent)}
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(record, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        _identity(path)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return record


def _old_locations(identity: dict) -> dict[str, str]:
    """Validate all old IDs before any destructive candidate operation."""
    locations = {}
    for role, canonical in CONTAINERS.items():
        backup_name = ROLLBACK_NAMES[role]
        original_id = identity["containers"][role]
        old_image = (identity["oldImageId"] if role != "caddy"
                     else None)
        current, saved = _inspect(canonical), _inspect(backup_name)
        matching = [(name, item) for name, item in ((canonical, current),
                     (backup_name, saved)) if item is not None and item.get("Id") == original_id]
        if len(matching) != 1 or (old_image is not None
                                  and matching[0][1].get("Image") != old_image):
            raise RollbackError("old_container_identity_missing")
        if saved is not None and saved.get("Id") != original_id:
            raise RollbackError("rollback_name_conflict")
        if (current is not None and current.get("Id") != original_id
                and current.get("Image") != identity["candidateImageId"]
                and role != "caddy"):
            raise RollbackError("candidate_name_conflict")
        if role == "caddy" and current is not None and current.get("Id") != original_id:
            project = current.get("Config", {}).get("Labels", {}).get(
                "com.docker.compose.project")
            if project != "atom-ip-ingress":
                raise RollbackError("candidate_caddy_identity_mismatch")
        locations[role] = matching[0][0]
    for name, project in EXTRA.items():
        item = _inspect(name)
        if item is not None and (item.get("Image") != identity["candidateImageId"]
                                 or item.get("Config", {}).get("Labels", {}).get(
                                     "com.docker.compose.project") != project):
            raise RollbackError("candidate_support_identity_mismatch")
    return locations


def _stop_remove_candidate(name: str, expected_image: str | None) -> None:
    item = _inspect(name)
    if item is None:
        return
    if expected_image is not None and item.get("Image") != expected_image:
        raise RollbackError("candidate_image_mismatch")
    _run("container", "stop", "--time", "90", name)
    _run("container", "rm", name)


def _start_if_needed(name: str) -> None:
    item = _inspect(name)
    if item is None:
        raise RollbackError("old_container_missing")
    if item.get("State", {}).get("Running") is not True:
        _run("container", "start", name)


def _await_healthy(name: str, *, seconds: int = 150) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        item = _inspect(name)
        if item is not None and item.get("State", {}).get("Health", {}).get("Status") == "healthy":
            return
        time.sleep(2)
    raise RollbackError("old_pair_health_timeout")


def _await_console(url: str, *, seconds: int = 60) -> None:
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme == "https" and parsed.hostname is not None
                 and ip_address(parsed.hostname).compressed == parsed.hostname
                 and parsed.port is None and parsed.path == "/atom/"
                 and not parsed.query and not parsed.fragment
                 and parsed.username is None and parsed.password is None)
    except ValueError:
        valid = False
    if not valid:
        raise RollbackError("invalid_console_probe")
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context()))
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with opener.open(Request(url, headers={"Accept": "text/html"}), timeout=5) as response:
                if response.status == 200 and response.headers.get_content_type() == "text/html":
                    return
        except (HTTPError, URLError, TimeoutError, OSError):
            pass
        time.sleep(2)
    raise RollbackError("old_console_probe_timeout")


def rollback(identity: dict, *, console_url: str) -> None:
    locations = _old_locations(identity)
    # The broker must release its Docker-daemon lease before the preserved
    # broker with the same identity starts again.
    for role in ("broker", "api"):
        canonical = CONTAINERS[role]
        if locations[role] != canonical:
            _stop_remove_candidate(canonical, identity["candidateImageId"])
            _run("container", "rename", ROLLBACK_NAMES[role], canonical)
    _start_if_needed(CONTAINERS["api"])
    _start_if_needed(CONTAINERS["broker"])
    _await_healthy(CONTAINERS["api"])
    _await_healthy(CONTAINERS["broker"])

    # Restore the old Caddy only after the old API is answering. An unfinished
    # cutover may have left the original Caddy active; keep it in that case.
    if locations["caddy"] != CONTAINERS["caddy"]:
        new_caddy = _inspect(CONTAINERS["caddy"])
        if new_caddy is not None:
            project = new_caddy.get("Config", {}).get("Labels", {}).get(
                "com.docker.compose.project")
            if project != "atom-ip-ingress":
                raise RollbackError("candidate_caddy_identity_mismatch")
            _stop_remove_candidate(CONTAINERS["caddy"], None)
        _run("container", "rename", ROLLBACK_NAMES["caddy"], CONTAINERS["caddy"])
    _start_if_needed(CONTAINERS["caddy"])
    _await_console(console_url)

    # Remove only Compose-labelled candidate support services after old 443
    # routing has recovered. Unknown same-name containers are left untouched.
    for name, project in EXTRA.items():
        item = _inspect(name)
        if item is None:
            continue
        if (item.get("Image") != identity["candidateImageId"] or
                item.get("Config", {}).get("Labels", {}).get(
                    "com.docker.compose.project") != project):
            raise RollbackError("candidate_support_identity_mismatch")
        _stop_remove_candidate(name, identity["candidateImageId"])
    for role, name in CONTAINERS.items():
        item = _inspect(name)
        if item is None or item.get("Id") != identity["containers"][role]:
            raise RollbackError("restored_container_identity_mismatch")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("capture", "rollback"))
    parser.add_argument("--identity", required=True, type=Path)
    parser.add_argument("--console-url")
    parser.add_argument("--revision")
    parser.add_argument("--candidate-image")
    arguments = parser.parse_args(argv)
    try:
        with host_lock():
            if arguments.mode == "capture":
                if arguments.revision is None or arguments.candidate_image is None:
                    raise RollbackError("missing_capture_inputs")
                capture_identity(arguments.identity, revision=arguments.revision,
                                 candidate_image=arguments.candidate_image)
                print("old_container_identity_recorded")
                return 0
            if arguments.console_url is None:
                raise RollbackError("missing_console_probe")
            identity = _identity(arguments.identity)
            ledger = PhaseLedger(Path(identity["stateDirectory"]), identity["revision"])
            ledger.write(outcome="rollback_started", image_id=identity["candidateImageId"],
                         details={"oldImageId": identity["oldImageId"]})
            try:
                rollback(identity, console_url=arguments.console_url)
            except RollbackError as exc:
                ledger.write(outcome="rollback_failed", image_id=identity["candidateImageId"],
                             details={"reason": str(exc)})
                raise
            ledger.write(outcome="rolled_back", image_id=identity["candidateImageId"],
                         details={"oldImageId": identity["oldImageId"]})
    except (RollbackError, CutoverError, OSError) as exc:
        print(str(exc) if isinstance(exc, (RollbackError, CutoverError))
              else "rollback_io_failed", file=sys.stderr)
        return 2
    print("old_pair_restored")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
