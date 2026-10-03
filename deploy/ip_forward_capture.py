"""Capture a schema-18 successor only after exact-ID writer exclusion.

This module is an internal phase of the forward transaction, not an operator
command. Its caller retains the host lock and is responsible for recovery.
It refuses to copy until maintenance ingress and all five stopped writer IDs
are verified again at the capture boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import stat
import sys

import ip_cutover_apply
import ip_forward_preflight
import ip_forward_writers
import paired_backup
import protected_cutover

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.ip_ingress import (IngressError, IpIngressConfig,
                            probe_ip_maintenance_routes,
                            render_ip_maintenance_routes)
from app.project_origins import OriginRoute


class CaptureError(RuntimeError):
    """Stable, credential-free forward capture failure code."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise CaptureError(code)


@dataclass(frozen=True)
class CapturedGeneration:
    backup: Path
    candidate: Path
    manifest_sha256: str
    caddy_sha256: str
    artifact_count: int
    origin_count: int


def _private_path(path: Path, *, directory: bool) -> None:
    try:
        protected_cutover._trusted_parents(path)
        info = path.lstat()
    except (OSError, protected_cutover.CutoverError) as exc:
        raise CaptureError("forward_source_unavailable") from exc
    _require((stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
             and info.st_uid == 0 and stat.S_IMODE(info.st_mode)
             == (0o700 if directory else 0o600), "insecure_forward_source")


def _maintenance(config: protected_cutover.CutoverConfig, *, source: Path,
                 caddy_id: str, publication: dict[str, str],
                 routes: tuple[OriginRoute, ...]) -> str:
    directory = source / "caddy"
    base, active = directory / "Caddyfile.base", directory / "Caddyfile"
    _private_path(directory, directory=True)
    _private_path(base, directory=False)
    _private_path(active, directory=False)
    item = protected_cutover._inspect(config.docker, "container", "atom-tls")
    _require(item.get("Id") == caddy_id
             and item.get("State", {}).get("Running") is True,
             "maintenance_caddy_identity_changed")
    mounts = [mount for mount in item.get("Mounts") or ()
              if mount.get("Destination") == "/etc/caddy"]
    _require(len(mounts) == 1 and mounts[0].get("Source") == str(directory)
             and mounts[0].get("Type") == "bind" and mounts[0].get("RW") is False,
             "maintenance_caddy_bind_changed")
    address = publication["ATOM_PUBLIC_IP"]
    acme = publication["ATOM_ACME_DIRECTORY"]
    expected_base = ip_cutover_apply._maintenance_caddyfile(address, acme)
    _require(base.read_bytes() == expected_base, "maintenance_console_file_mismatch")
    ingress = IpIngressConfig(address, publication["ATOM_PREVIEW_UPSTREAM"],
                              publication["ATOM_PUBLIC_UPSTREAM"], acme)
    try:
        expected = render_ip_maintenance_routes(expected_base.decode("utf-8"),
                                                 routes, ingress).encode("utf-8")
    except IngressError as exc:
        raise CaptureError("maintenance_origin_file_invalid") from exc
    _require(active.read_bytes() == expected, "maintenance_origin_file_mismatch")
    ip_cutover_apply._maintenance_probe(address)
    probe_ip_maintenance_routes(routes, address)
    return hashlib.sha256(expected).hexdigest()


def capture(*, config: protected_cutover.CutoverConfig,
            active: dict[str, object], publication: dict[str, str],
            stopped: ip_forward_writers.StoppedWriters,
            routes: tuple[OriginRoute, ...], successor_revision: str) -> CapturedGeneration:
    """Verify exclusion, then make and independently restore a fresh pair."""
    _require(protected_cutover.REVISION.fullmatch(successor_revision) is not None
             and type(active) is dict and type(publication) is dict
             and isinstance(stopped, ip_forward_writers.StoppedWriters)
             and type(routes) is tuple and isinstance(config, protected_cutover.CutoverConfig),
             "invalid_forward_capture")
    _require(type(active.get("revision")) is str
             and protected_cutover.REVISION.fullmatch(active["revision"]) is not None
             and active["revision"] != successor_revision
             and all(publication.get(key)
             for key in ("ATOM_PUBLIC_IP", "ATOM_ACME_DIRECTORY",
                         "ATOM_PREVIEW_UPSTREAM", "ATOM_PUBLIC_UPSTREAM",
                         "ATOM_FIRST_PORT", "ATOM_LAST_PORT")),
             "invalid_forward_capture")
    _require(type(active.get("candidateDirectory")) is str,
             "forward_source_identity_mismatch")
    source = Path(active["candidateDirectory"])
    ids = active.get("containerIds")
    image = active.get("imageId")
    _require(source.is_absolute() and type(ids) is dict
             and type(image) is str and protected_cutover.IMAGE.fullmatch(image)
             and ids.get("caddy") and stopped.ids == {
                 role: ids.get(role) for role in ip_forward_writers.STOP_ORDER},
             "forward_source_identity_mismatch")
    _private_path(source, directory=True)
    try:
        first, last = int(publication["ATOM_FIRST_PORT"]), int(
            publication["ATOM_LAST_PORT"])
        _require(1024 <= first < last <= 65535 and last - first + 1 <= 512,
                 "invalid_forward_capture")
        for role in ip_forward_writers.STOP_ORDER:
            ip_forward_writers._identity(config, role, stopped.ids[role], running=False)
        actual_routes = ip_forward_preflight._active_routes(
            source / "data" / "atom.db", first, last)
        _require(actual_routes == routes, "forward_origin_ledger_changed")
        caddy_digest = _maintenance(config, source=source, caddy_id=ids["caddy"],
                                    publication=publication, routes=routes)
        protected_cutover._database(source / "data" / "atom.db", 18, broker=False)
        protected_cutover._database(source / "broker" / "registry.db", 3,
                                    broker=True)
    except (ip_cutover_apply.ApplyError, IngressError,
            protected_cutover.CutoverError, ip_forward_writers.WriterError,
            ip_forward_preflight.ForwardPreflightError, ValueError) as exc:
        raise CaptureError("forward_capture_gate_failed") from exc
    prefix = successor_revision[:12]
    backup = config.backup_root / ("forward-pre-" + prefix)
    candidate = config.backup_root / ("forward-candidate-" + prefix)
    _require(not backup.exists() and not candidate.exists()
             and backup != source and candidate != source,
             "forward_capture_destination_exists")
    try:
        captured = paired_backup.capture(data=source / "data", broker=source / "broker",
            caddy=source / "caddy" / "Caddyfile", destination=backup,
            image_id=image, app_schema=18, broker_schema=3)
        checked = paired_backup.verify(backup)
        _require(captured == checked and checked.get("status") == "verified",
                 "forward_backup_mismatch")
        restored = paired_backup.restore(backup, candidate)
        _require(restored == checked, "forward_restore_mismatch")
        _require(checked["counts"]["data"]["project_origin_ports"] == len(routes),
                 "forward_origin_count_mismatch")
    except (paired_backup.BackupError, OSError, ValueError) as exc:
        raise CaptureError("forward_backup_failed") from exc
    return CapturedGeneration(backup, candidate, checked["manifestSha256"],
                              caddy_digest,
                              checked["counts"]["data"]["revision_artifacts"],
                              len(routes))
