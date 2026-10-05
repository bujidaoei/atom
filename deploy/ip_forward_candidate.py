"""Prepare a separately restored schema-18 candidate before container handoff.

The source generation stays stopped behind TLS maintenance. This phase never
renames, starts or removes a container and never changes the captured data or
broker directories; failure leaves those directories for inspection.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
import sys

import ip_cutover_apply
import ip_cutover_env
import ip_forward_identity
import ip_forward_preflight
import ip_forward_stage
import ip_forward_writers
import paired_backup
import protected_cutover

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.ip_ingress import (IngressError, IpIngressConfig,
                            render_ip_maintenance_routes)  # noqa: E402


class CandidateError(RuntimeError):
    """Stable, credential-free preparation failure code."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise CandidateError(code)


@dataclass(frozen=True)
class PreparedCandidate:
    directory: Path
    compose_env: Path
    api_env: Path
    broker_env: Path
    caddy_ip: str
    service_ips: dict[str, str]
    maintenance_sha256: str


def _private_directory(path: Path, *, create: bool = False) -> None:
    _require(path.is_absolute() and ".." not in path.parts,
             "invalid_forward_candidate_path")
    try:
        protected_cutover._trusted_parents(path)
        if create:
            path.mkdir(mode=0o700)
        info = path.lstat()
    except (OSError, protected_cutover.CutoverError) as exc:
        raise CandidateError("forward_candidate_directory_unavailable") from exc
    _require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0
             and stat.S_IMODE(info.st_mode) == 0o700,
             "insecure_forward_candidate_directory")


def _private_bytes(path: Path, payload: bytes) -> None:
    _require(path.is_absolute() and type(payload) is bytes
             and 0 < len(payload) <= 1024 * 1024,
             "invalid_forward_candidate_file")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _source_handoff(config: protected_cutover.CutoverConfig,
                    stage: ip_forward_stage.ForwardStage,
                    service_ips: dict[str, str]) -> None:
    """Stopped writer IDs and still-running TLS ID match the sealed identity."""
    _require(stage.stopped.ids == {role: stage.active["containerIds"][role]
                                   for role in ip_forward_writers.STOP_ORDER},
             "forward_stopped_identity_mismatch")
    for role in ip_forward_writers.STOP_ORDER:
        ip_forward_writers._identity(
            config, role, stage.stopped.ids[role], running=False)
    caddy = protected_cutover._inspect(config.docker, "container", "atom-tls")
    _require(caddy.get("Name") == "/atom-tls"
             and caddy.get("Id") == stage.active["containerIds"]["caddy"]
             and caddy.get("State", {}).get("Running") is True
             and ip_forward_identity._pinned_address(caddy, config.network)
             == service_ips["caddy"],
             "forward_caddy_identity_changed")


def prepare(*, config: protected_cutover.CutoverConfig,
            stage: ip_forward_stage.ForwardStage,
            successor_source: Path, successor_revision: str,
            successor_image: str) -> PreparedCandidate:
    """Validate the captured pair, then create only private candidate inputs."""
    _require(getattr(os, "geteuid", lambda: -1)() == 0,
             "root_required")
    _require(isinstance(config, protected_cutover.CutoverConfig)
             and isinstance(stage, ip_forward_stage.ForwardStage)
             and successor_source.is_absolute()
             and protected_cutover.REVISION.fullmatch(successor_revision) is not None
             and protected_cutover.IMAGE.fullmatch(successor_image) is not None,
             "invalid_forward_candidate")
    journal_record = stage.journal.read()
    _require(journal_record is not None
             and journal_record["phase"] == "captured"
             and journal_record["capture"] ==
             ip_forward_stage._receipt(stage.captured),
             "forward_capture_receipt_mismatch")
    identity = ip_forward_identity.read(
        stage.journal.identity_path, config=config,
        successor_revision=successor_revision)
    source, backup, candidate = (Path(identity[key]) for key in
                                 ("sourceDirectory", "backupDirectory",
                                  "candidateDirectory"))
    _require(source == Path(stage.active["candidateDirectory"])
             and backup == stage.captured.backup
             and candidate == stage.captured.candidate
             and identity["successorImageId"] == successor_image
             and identity["sourceImageId"] == stage.active["imageId"],
             "forward_candidate_identity_mismatch")
    service_ips = identity["serviceIps"]
    _source_handoff(config, stage, service_ips)
    _private_directory(candidate)
    _private_directory(backup)
    verified = paired_backup.verify(backup)
    restored = paired_backup.verify(candidate)
    _require(verified == restored
             and verified["manifestSha256"] == stage.captured.manifest_sha256
             and verified["oldImageId"] == stage.active["imageId"]
             and verified["schemas"] == {"data": 18, "broker": 3},
             "forward_candidate_pair_mismatch")
    protected_cutover._database(candidate / "data" / "atom.db", 18,
                                broker=False)
    protected_cutover._database(candidate / "broker" / "registry.db", 3,
                                broker=True)
    publication = stage.publication
    routes = ip_forward_preflight._active_routes(
        candidate / "data" / "atom.db",
        int(publication["ATOM_FIRST_PORT"]),
        int(publication["ATOM_LAST_PORT"]))
    _require(routes == stage.routes,
             "forward_candidate_origins_mismatch")
    caddy_file = candidate / "Caddyfile"
    _require(caddy_file.is_file() and not caddy_file.is_symlink()
             and hashlib.sha256(caddy_file.read_bytes()).hexdigest()
             == stage.captured.caddy_sha256,
             "forward_candidate_caddy_mismatch")
    address = service_ips["caddy"]
    maintenance = ip_cutover_apply._maintenance_caddyfile(
        publication["ATOM_PUBLIC_IP"], publication["ATOM_ACME_DIRECTORY"])
    ingress = IpIngressConfig(publication["ATOM_PUBLIC_IP"],
                              publication["ATOM_PREVIEW_UPSTREAM"],
                              publication["ATOM_PUBLIC_UPSTREAM"],
                              publication["ATOM_ACME_DIRECTORY"])
    try:
        active = render_ip_maintenance_routes(
            maintenance.decode("utf-8"), routes, ingress).encode("utf-8")
    except (UnicodeError, IngressError) as exc:
        raise CandidateError("forward_candidate_ingress_invalid") from exc
    _require(active == caddy_file.read_bytes(),
             "forward_candidate_caddy_mismatch")
    caddy_dir = candidate / "caddy"
    _private_directory(caddy_dir, create=True)
    for filename, payload in (
            ("Caddyfile.base", maintenance),
            ("Caddyfile", active),
            ("Caddyfile.console", ip_forward_identity.caddy_bytes(
                identity, "base"))):
        _private_bytes(caddy_dir / filename, payload)
    private_env = candidate / "private-env"
    _private_directory(private_env, create=True)
    api_env, broker_env = ip_cutover_env.build(
        old_api=config.api, old_broker=config.broker,
        storage_file=Path(publication["ATOM_STORAGE_ENV_FILE"]),
        verifier_file=Path(publication["ATOM_VERIFIER_ENV_FILE"]),
        output_dir=private_env, candidate_image=successor_image,
        worker_image=publication["ATOM_VERIFIER_WORKER_IMAGE"],
        seccomp_file=Path(publication["ATOM_VERIFIER_POLICY_PATH"]),
        public_ip=publication["ATOM_PUBLIC_IP"],
        first_port=int(publication["ATOM_FIRST_PORT"]),
        last_port=int(publication["ATOM_LAST_PORT"]))
    current_publication = dict(publication)
    current_publication.update({
        "ATOM_CANDIDATE_API_IP": service_ips["api"],
        "ATOM_PREVIEW_SERVICE_IP": service_ips["preview"],
        "ATOM_PUBLIC_SERVICE_IP": service_ips["public"],
    })
    compose_env = ip_cutover_apply._compose_environment(
        current_publication, candidate, successor_image, address)
    return PreparedCandidate(candidate, compose_env, api_env, broker_env,
                             address, service_ips,
                             hashlib.sha256(active).hexdigest())
