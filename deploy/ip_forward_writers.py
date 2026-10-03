"""Exact-ID writer quiescence for a host-locked forward deployment.

The caller must first verify strict-TLS maintenance on the console and all
committed project origins and keep the host deployment lock held. This module
never switches ingress or deletes a container. A failed stop restarts only
the original IDs that this call stopped, in dependency order.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import time

import protected_cutover


STOP_ORDER = ("verifier", "preview", "public", "broker", "api")
SUPPORT_NAMES = {"preview": "atom-preview", "public": "atom-public",
                 "verifier": "atom-verifier"}
GRACE = {"verifier": 75, "preview": 30, "public": 30,
         "broker": 90, "api": 30}


class WriterError(RuntimeError):
    """Stable, credential-free writer transition failure code."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise WriterError(code)


def _run(docker: Path, *args: str, timeout: int = 120) -> None:
    try:
        result = subprocess.run([str(docker), *args], capture_output=True,
                                timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WriterError("writer_docker_unavailable") from exc
    _require(result.returncode == 0, "writer_docker_command_failed")


def _identity(config: protected_cutover.CutoverConfig,
              role: str, expected_id: str, *, running: bool | None) -> dict:
    name = (config.api if role == "api" else config.broker if role == "broker"
            else SUPPORT_NAMES[role])
    try:
        item = protected_cutover._inspect(config.docker, "container", name)
    except protected_cutover.CutoverError as exc:
        raise WriterError("writer_identity_unavailable") from exc
    _require(item.get("Name") == "/" + name
             and item.get("Id") == expected_id
             and (running is None or item.get("State", {}).get("Running") is running),
             "writer_identity_changed")
    return item


def _healthy(config: protected_cutover.CutoverConfig,
             role: str, expected_id: str, *, seconds: int = 150) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        item = _identity(config, role, expected_id, running=True)
        if item.get("State", {}).get("Health", {}).get("Status") == "healthy":
            return
        time.sleep(2)
    raise WriterError("writer_health_timeout")


@dataclass(frozen=True)
class StoppedWriters:
    ids: dict[str, str]


def resume(config: protected_cutover.CutoverConfig, stopped: StoppedWriters) -> None:
    """Restart the exact stopped generation; API precedes its network-sharing broker."""
    _require(isinstance(stopped, StoppedWriters)
             and set(stopped.ids) == set(STOP_ORDER), "invalid_writer_receipt")
    for role in reversed(STOP_ORDER):
        expected_id = stopped.ids[role]
        item = _identity(config, role, expected_id, running=None)
        if item.get("State", {}).get("Running") is not True:
            _run(config.docker, "container", "start", expected_id, timeout=45)
        _healthy(config, role, expected_id)


def stop(config: protected_cutover.CutoverConfig,
         container_ids: dict[str, str], candidate: Path) -> StoppedWriters:
    """Stop five exact current IDs, verify schema/idle state and recover on failure.

    The caller must keep the host lock and verified TLS maintenance active from
    before this call until the paired backup completes. This operation does not
    stop Caddy so existing certificates and 503 routes remain available.
    """
    _require(type(container_ids) is dict and set(STOP_ORDER) <= set(container_ids)
             and isinstance(candidate, Path) and candidate.is_absolute(),
             "invalid_writer_source")
    ids = {role: container_ids[role] for role in STOP_ORDER}
    _require(all(type(value) is str and len(value) == 64
                 and all(char in "0123456789abcdef" for char in value)
                 for role, value in ids.items()), "invalid_writer_identity")
    attempted: list[str] = []
    try:
        for role in STOP_ORDER:
            _identity(config, role, ids[role], running=True)
            attempted.append(role)
            _run(config.docker, "container", "stop", "--time", str(GRACE[role]),
                 ids[role], timeout=GRACE[role] + 20)
            _identity(config, role, ids[role], running=False)
        protected_cutover._database(candidate / "data" / "atom.db", 18, broker=False)
        protected_cutover._database(candidate / "broker" / "registry.db", 3,
                                    broker=True)
    except BaseException as failure:
        try:
            for role in reversed(attempted):
                item = _identity(config, role, ids[role], running=None)
                if item.get("State", {}).get("Running") is not True:
                    _run(config.docker, "container", "start", ids[role], timeout=45)
                _healthy(config, role, ids[role])
        except BaseException as recovery_failure:
            raise WriterError("writer_recovery_failed") from recovery_failure
        raise WriterError("writer_stop_failed") from failure
    return StoppedWriters(ids)
