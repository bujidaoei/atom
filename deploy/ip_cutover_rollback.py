"""Restore the preserved old container pair after a failed IP publication cutover.

The old containers and schema-10 data are never rebuilt or migrated in place.
This command uses recorded Docker IDs, not names alone, before it removes a
candidate or starts the old pair. The new data directory remains for diagnosis.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
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

import candidate_write_fence
from protected_cutover import CutoverError, PhaseLedger, host_lock


IDENTITY = re.compile(r"[0-9a-f]{64}\Z")
IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,80}\Z")
DEFAULT_CONTAINERS = {
    "api": "atom-candidate", "broker": "atom-candidate-broker", "caddy": "atom-tls",
}
DEFAULT_EXTRA = {"preview": "atom-preview", "public": "atom-public",
                 "verifier": "atom-verifier"}
EXTRA_PROJECTS = {"preview": "atom-ip-publication", "public": "atom-ip-publication",
                  "verifier": "atom-ip-verifier"}
DEFAULT_NAMES = DEFAULT_CONTAINERS | DEFAULT_EXTRA


def _names(value: object) -> dict[str, str]:
    if (type(value) is not dict or set(value) != set(DEFAULT_NAMES)
            or any(type(name) is not str or NAME.fullmatch(name) is None
                   or len(name) > 70 for name in value.values())
            or len(set(value.values())) != len(value)
            or any(name + "-rollback" in value.values()
                   for name in value.values())):
        raise RollbackError("invalid_container_names")
    return value


def _rollback_name(name: str) -> str:
    return name + "-rollback"


class RollbackError(RuntimeError):
    """Stable non-secret code suitable for a phase receipt."""


def _record_phase(ledger: PhaseLedger, *, outcome: str,
                  image_id: str, details: dict[str, object],
                  history_phase: str | None = None) -> None:
    previous = ledger.read()
    history = [] if previous is None else previous.get("phaseHistory", [])
    if type(history) is not list or len(history) >= 32:
        raise RollbackError("invalid_phase_history")
    event = {"phase": history_phase or outcome,
             "at": datetime.now(timezone.utc).isoformat(),
             "details": details}
    retained = {} if previous is None else {
        key: value for key, value in previous.items()
        if key not in {"schemaVersion", "revision", "imageId", "outcome",
                       "updatedAt", "phaseHistory"}}
    ledger.write(outcome=outcome, image_id=image_id,
                 details={**retained, **details,
                          "phaseHistory": [*history, event]})


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
            "containers", "stateDirectory", "names"} or record["schemaVersion"] != 2
            or not isinstance(record["revision"], str)
            or re.fullmatch(r"[0-9a-f]{40}", record["revision"]) is None
            or any(not isinstance(record[key], str) or IMAGE.fullmatch(record[key]) is None
                   for key in ("oldImageId", "candidateImageId"))
            or type(record["containers"]) is not dict
            or set(record["containers"]) != set(DEFAULT_CONTAINERS)
            or any(not isinstance(value, str) or IDENTITY.fullmatch(value) is None
                   for value in record["containers"].values())
            or not isinstance(record["stateDirectory"], str)
            or not Path(record["stateDirectory"]).is_absolute()):
        raise RollbackError("invalid_rollback_identity")
    _names(record["names"])
    return record


def _names_file(path: Path) -> dict[str, str]:
    info = path.lstat()
    if (not path.is_absolute() or not stat.S_ISREG(info.st_mode)
            or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600):
        raise RollbackError("insecure_names_file")
    try:
        return _names(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, ValueError) as exc:
        raise RollbackError("invalid_names_file") from exc


def capture_identity(path: Path, *, revision: str, candidate_image: str,
                     names: dict[str, str] | None = None) -> dict:
    """Persist the current old IDs before a writer is stopped or renamed."""
    if (not path.is_absolute() or not isinstance(revision, str)
            or re.fullmatch(r"[0-9a-f]{40}", revision) is None
            or not isinstance(candidate_image, str)
            or IMAGE.fullmatch(candidate_image) is None):
        raise RollbackError("invalid_identity_capture")
    names = _names(names if names is not None else DEFAULT_NAMES)
    parent = path.parent
    info = parent.stat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise RollbackError("insecure_identity_directory")
    containers = {}
    old_image = None
    for role in DEFAULT_CONTAINERS:
        name = names[role]
        item = _inspect(name)
        if (item is None or item.get("State", {}).get("Running") is not True
                or not isinstance(item.get("Id"), str)
                or IDENTITY.fullmatch(item["Id"]) is None
                or _inspect(_rollback_name(name)) is not None):
            raise RollbackError("old_container_not_ready")
        if role != "caddy":
            if old_image is None:
                old_image = item.get("Image")
            elif old_image != item.get("Image"):
                raise RollbackError("old_pair_image_mismatch")
        containers[role] = item["Id"]
    if (not isinstance(old_image, str) or IMAGE.fullmatch(old_image) is None
            or old_image == candidate_image
            or any(_inspect(names[role]) is not None for role in EXTRA_PROJECTS)):
        raise RollbackError("candidate_not_isolated")
    record = {"schemaVersion": 2, "revision": revision, "oldImageId": old_image,
              "candidateImageId": candidate_image, "containers": containers,
              "stateDirectory": str(parent), "names": names}
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
    names = _names(identity["names"])
    for role in DEFAULT_CONTAINERS:
        canonical = names[role]
        backup_name = _rollback_name(canonical)
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
    for role, project in EXTRA_PROJECTS.items():
        name = names[role]
        item = _inspect(name)
        if item is not None and (item.get("Image") != identity["candidateImageId"]
                                 or item.get("Config", {}).get("Labels", {}).get(
                                     "com.docker.compose.project") != project):
            raise RollbackError("candidate_support_identity_mismatch")
    return locations


def _stop_remove_candidate(name: str, expected_image: str | None,
                           *, grace_seconds: int) -> None:
    item = _inspect(name)
    if item is None:
        return
    if expected_image is not None and item.get("Image") != expected_image:
        raise RollbackError("candidate_image_mismatch")
    if type(grace_seconds) is not int or not 1 <= grace_seconds <= 90:
        raise RollbackError("invalid_stop_grace")
    _run("container", "stop", "--time", str(grace_seconds), name,
         timeout=grace_seconds + 15)
    _run("container", "rm", name)


def _start_if_needed(name: str) -> None:
    item = _inspect(name)
    if item is None:
        raise RollbackError("old_container_missing")
    if item.get("State", {}).get("Running") is not True:
        _run("container", "start", name)


def _baseline(identity: dict) -> dict:
    path = Path(identity["stateDirectory"]) / (identity["revision"] + ".baseline.json")
    try:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or stat.S_IMODE(info.st_mode) != 0o600):
            raise RollbackError("insecure_candidate_baseline")
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise RollbackError("candidate_baseline_missing") from exc
    if (type(record) is not dict or set(record) != {
            "schemaVersion", "revision", "candidateImageId",
            "candidateDirectory", "stateSha256"} or record["schemaVersion"] != 1
            or record["revision"] != identity["revision"]
            or record["candidateImageId"] != identity["candidateImageId"]
            or type(record["stateSha256"]) is not str
            or IDENTITY.fullmatch(record["stateSha256"]) is None
            or type(record["candidateDirectory"]) is not str
            or not Path(record["candidateDirectory"]).is_absolute()):
        raise RollbackError("invalid_candidate_baseline")
    return record


def _fence_candidate(identity: dict, locations: dict[str, str],
                     *, console_url: str, ca_file: Path | None) -> None:
    names = _names(identity["names"])
    baseline_path = (Path(identity["stateDirectory"])
                     / (identity["revision"] + ".baseline.json"))
    if locations["caddy"] == names["caddy"] and not baseline_path.exists():
        # The candidate was never exposed, and the old ingress is still fenced.
        return
    baseline = _baseline(identity)  # Fail before service disruption.
    running = {role: (item is not None and item.get("State", {}).get("Running") is True)
               for role, item in ((role, _inspect(names[role]))
                                  for role in ("caddy", "broker", "api"))}
    try:
        for role, grace in (("caddy", 15), ("broker", 90), ("api", 30)):
            if running[role]:
                _run("container", "stop", "--time", str(grace), names[role],
                     timeout=grace + 15)
        try:
            observed = candidate_write_fence.candidate_fingerprint(
                Path(baseline["candidateDirectory"]))
        except candidate_write_fence.FenceError as exc:
            raise RollbackError("candidate_state_unavailable") from exc
        if observed != baseline["stateSha256"]:
            raise RollbackError("candidate_has_unmerged_writes")
    except BaseException:
        # A refusal must leave the live generation serving, including its TLS ingress.
        for role in ("api", "broker", "caddy"):
            if running[role]:
                _start_if_needed(names[role])
        for role in ("api", "broker"):
            if running[role]:
                _await_healthy(names[role])
        if running["caddy"]:
            _await_console(console_url, ca_file=ca_file)
        raise


def _await_healthy(name: str, *, seconds: int = 150) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        item = _inspect(name)
        if item is not None and item.get("State", {}).get("Health", {}).get("Status") == "healthy":
            return
        time.sleep(2)
    raise RollbackError("old_pair_health_timeout")


def _await_console(url: str, *, ca_file: Path | None = None,
                   seconds: int = 60) -> None:
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme == "https" and parsed.hostname is not None
                 and ip_address(parsed.hostname).compressed == parsed.hostname
                 and (parsed.port is None or 1024 <= parsed.port <= 65535)
                 and parsed.path == "/atom/"
                 and not parsed.query and not parsed.fragment
                 and parsed.username is None and parsed.password is None)
    except ValueError:
        valid = False
    if not valid:
        raise RollbackError("invalid_console_probe")
    if ca_file is not None and (not ca_file.is_absolute() or not ca_file.is_file()
                                or ca_file.is_symlink()):
        raise RollbackError("invalid_console_ca")
    try:
        context = ssl.create_default_context(cafile=str(ca_file) if ca_file else None)
    except (OSError, ssl.SSLError) as exc:
        raise RollbackError("invalid_console_ca") from exc
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context))
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


def rollback(identity: dict, *, console_url: str,
             ca_file: Path | None = None) -> None:
    locations = _old_locations(identity)
    names = _names(identity["names"])
    _fence_candidate(identity, locations, console_url=console_url, ca_file=ca_file)
    # The broker must release its Docker-daemon lease before the preserved
    # broker with the same identity starts again.
    for role in ("broker", "api"):
        canonical = names[role]
        if locations[role] != canonical:
            _stop_remove_candidate(canonical, identity["candidateImageId"],
                                   grace_seconds=90 if role == "broker" else 30)
            _run("container", "rename", _rollback_name(canonical), canonical)
    _start_if_needed(names["api"])
    _start_if_needed(names["broker"])
    _await_healthy(names["api"])
    _await_healthy(names["broker"])

    # Restore the old Caddy only after the old API is answering. An unfinished
    # cutover may have left the original Caddy active; keep it in that case.
    if locations["caddy"] != names["caddy"]:
        new_caddy = _inspect(names["caddy"])
        if new_caddy is not None:
            project = new_caddy.get("Config", {}).get("Labels", {}).get(
                "com.docker.compose.project")
            if project != "atom-ip-ingress":
                raise RollbackError("candidate_caddy_identity_mismatch")
            _stop_remove_candidate(names["caddy"], None, grace_seconds=15)
        _run("container", "rename", _rollback_name(names["caddy"]), names["caddy"])
    _start_if_needed(names["caddy"])
    _await_console(console_url, ca_file=ca_file)

    # Remove only Compose-labelled candidate support services after old 443
    # routing has recovered. Unknown same-name containers are left untouched.
    for role, project in EXTRA_PROJECTS.items():
        name = names[role]
        item = _inspect(name)
        if item is None:
            continue
        if (item.get("Image") != identity["candidateImageId"] or
                item.get("Config", {}).get("Labels", {}).get(
                    "com.docker.compose.project") != project):
            raise RollbackError("candidate_support_identity_mismatch")
        _stop_remove_candidate(name, identity["candidateImageId"],
                               grace_seconds=75 if role == "verifier" else 15)
    for role in DEFAULT_CONTAINERS:
        name = names[role]
        item = _inspect(name)
        if item is None or item.get("Id") != identity["containers"][role]:
            raise RollbackError("restored_container_identity_mismatch")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("capture", "rollback"))
    parser.add_argument("--identity", required=True, type=Path)
    parser.add_argument("--console-url")
    parser.add_argument("--ca-file", type=Path)
    parser.add_argument("--revision")
    parser.add_argument("--candidate-image")
    parser.add_argument("--names-file", type=Path)
    arguments = parser.parse_args(argv)
    try:
        with host_lock():
            if arguments.mode == "capture":
                if arguments.revision is None or arguments.candidate_image is None:
                    raise RollbackError("missing_capture_inputs")
                capture_identity(arguments.identity, revision=arguments.revision,
                                 candidate_image=arguments.candidate_image,
                                 names=(_names_file(arguments.names_file)
                                        if arguments.names_file is not None else None))
                print("old_container_identity_recorded")
                return 0
            if arguments.console_url is None:
                raise RollbackError("missing_console_probe")
            identity = _identity(arguments.identity)
            ledger = PhaseLedger(Path(identity["stateDirectory"]), identity["revision"])
            original = ledger.read()
            _record_phase(ledger, outcome="rollback_started",
                          image_id=identity["candidateImageId"],
                          details={"oldImageId": identity["oldImageId"]})
            try:
                rollback(identity, console_url=arguments.console_url,
                         ca_file=arguments.ca_file)
            except RollbackError as exc:
                refusal = (str(exc) == "candidate_has_unmerged_writes"
                           and original is not None
                           and original.get("outcome") == "awaiting_acceptance")
                _record_phase(
                    ledger,
                    outcome="awaiting_acceptance" if refusal else "rollback_failed",
                    history_phase="rollback_refused" if refusal else None,
                    image_id=identity["candidateImageId"],
                    details=({"lastRollbackResult": str(exc)} if refusal
                             else {"reason": str(exc)}))
                raise
            _record_phase(ledger, outcome="rolled_back",
                          image_id=identity["candidateImageId"],
                          details={"oldImageId": identity["oldImageId"]})
    except (RollbackError, CutoverError, OSError) as exc:
        print(str(exc) if isinstance(exc, (RollbackError, CutoverError))
              else "rollback_io_failed", file=sys.stderr)
        return 2
    print("old_pair_restored")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
