"""Retain six exact stopped source containers while freeing canonical names.

The caller holds the forward host lock and has already prepared the separate
candidate behind verified TLS maintenance. An ordinary pre-exposure failure
restores the exact source IDs and normal ingress before recording recovery.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess

import ip_forward_candidate
import ip_forward_identity
import ip_forward_stage
import ip_forward_writers
import protected_cutover


class HoldError(RuntimeError):
    """Stable, credential-free source-handoff failure code."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise HoldError(code)


@dataclass(frozen=True)
class HeldSource:
    ids: dict[str, str]
    names: dict[str, str]


def _run(config: protected_cutover.CutoverConfig, *arguments: str,
         timeout: int = 60) -> None:
    try:
        result = subprocess.run([str(config.docker), *arguments],
                                capture_output=True, timeout=timeout,
                                check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HoldError("forward_docker_unavailable") from exc
    _require(result.returncode == 0, "forward_docker_command_failed")


def _inspect(config: protected_cutover.CutoverConfig,
             expected_id: str, expected_name: str,
             *, running: bool | None) -> dict:
    try:
        item = protected_cutover._inspect(config.docker, "container", expected_id)
    except protected_cutover.CutoverError as exc:
        raise HoldError("forward_source_identity_unavailable") from exc
    _require(item.get("Id") == expected_id
             and item.get("Name") == "/" + expected_name
             and (running is None or item.get("State", {}).get("Running") is running),
             "forward_source_identity_changed")
    return item


def _canonical(config: protected_cutover.CutoverConfig, role: str) -> str:
    return ip_forward_identity._name(config, role)


def restore(*, config: protected_cutover.CutoverConfig,
            stage: ip_forward_stage.ForwardStage,
            identity: dict[str, object], publication_file: Path) -> None:
    """Pre-exposure recovery from any partially completed exact-ID rename."""
    try:
        for role in reversed(ip_forward_identity.ROLES):
            expected_id = identity["containerIds"][role]
            canonical = _canonical(config, role)
            held = identity["heldNames"][role]
            item = protected_cutover._inspect(config.docker, "container",
                                              expected_id)
            actual_name = item.get("Name")
            _require(actual_name in ("/" + canonical, "/" + held)
                     and item.get("Id") == expected_id,
                     "forward_source_identity_changed")
            if actual_name == "/" + held:
                _run(config, "container", "rename", expected_id, canonical)
            _inspect(config, expected_id, canonical, running=None)
        caddy_id = identity["containerIds"]["caddy"]
        caddy = _inspect(config, caddy_id, "atom-tls", running=None)
        if caddy.get("State", {}).get("Running") is not True:
            _run(config, "container", "start", caddy_id, timeout=45)
        _inspect(config, caddy_id, "atom-tls", running=True)
        ip_forward_stage._recover_pre_exposure(
            config=config, stopped=stage.stopped, controller=stage.controller,
            original_base=ip_forward_identity.caddy_bytes(identity, "base"),
            journal=stage.journal, active=stage.active,
            publication_file=publication_file,
            revision=identity["sourceRevision"])
    except BaseException as exc:
        raise HoldError("forward_held_source_recovery_failed") from exc


def hold(*, config: protected_cutover.CutoverConfig,
         stage: ip_forward_stage.ForwardStage,
         prepared: ip_forward_candidate.PreparedCandidate,
         successor_revision: str, publication_file: Path) -> HeldSource:
    """Stop TLS ingress and rename six stopped source IDs to reserved names."""
    _require(isinstance(config, protected_cutover.CutoverConfig)
             and isinstance(stage, ip_forward_stage.ForwardStage)
             and isinstance(prepared, ip_forward_candidate.PreparedCandidate)
             and isinstance(publication_file, Path)
             and publication_file.is_absolute(),
             "invalid_forward_handoff")
    identity = ip_forward_identity.read(
        stage.journal.identity_path, config=config,
        successor_revision=successor_revision)
    _require(stage.journal.read()["phase"] == "captured"
             and prepared.directory == Path(identity["candidateDirectory"])
             and prepared.service_ips == identity["serviceIps"]
             and stage.active["containerIds"] == identity["containerIds"],
             "forward_handoff_identity_mismatch")
    ip_forward_candidate._source_handoff(
        config, stage, identity["serviceIps"])
    ids = identity["containerIds"]
    for role in ip_forward_writers.STOP_ORDER:
        _inspect(config, ids[role], _canonical(config, role), running=False)
    _inspect(config, ids["caddy"], "atom-tls", running=True)
    try:
        stage.journal.advance("candidate_intent")
        _run(config, "container", "stop", "--time", "15",
             ids["caddy"], timeout=35)
        _inspect(config, ids["caddy"], "atom-tls", running=False)
        for role in ip_forward_identity.ROLES:
            expected_id = ids[role]
            canonical = _canonical(config, role)
            _inspect(config, expected_id, canonical, running=False)
            _run(config, "container", "rename", expected_id,
                 identity["heldNames"][role], timeout=30)
            _inspect(config, expected_id, identity["heldNames"][role],
                     running=False)
        return HeldSource(dict(ids), dict(identity["heldNames"]))
    except BaseException as failure:
        restore(config=config, stage=stage, identity=identity,
                publication_file=publication_file)
        raise HoldError("forward_source_handoff_failed") from failure
