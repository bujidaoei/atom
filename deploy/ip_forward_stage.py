"""Same-lock maintenance and quiesced capture phase of forward deployment.

This is an internal transaction phase. Its caller holds the host cutover lock
from preflight through candidate handoff or source recovery. It has no CLI:
exposing only this half of a deployment would leave the console unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

import ip_cutover_apply
import ip_forward_capture
import ip_forward_identity
import ip_forward_journal
import ip_forward_preflight
import ip_forward_writers
import protected_cutover

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.ip_ingress import IpIngressConfig  # noqa: E402
from app.ip_ingress_controller import DockerCaddy, IpIngressController  # noqa: E402
from app.project_origins import ProjectOriginRepository  # noqa: E402


class StageError(RuntimeError):
    """Stable, credential-free forward staging failure code."""


@dataclass(frozen=True)
class ForwardStage:
    active: dict[str, object]
    publication: dict[str, str]
    routes: tuple
    stopped: ip_forward_writers.StoppedWriters
    captured: ip_forward_capture.CapturedGeneration
    journal: ip_forward_journal.ForwardJournal
    controller: IpIngressController


def _controller(*, config: protected_cutover.CutoverConfig,
                publication: dict[str, str], source: Path) -> IpIngressController:
    first, last = int(publication["ATOM_FIRST_PORT"]), int(
        publication["ATOM_LAST_PORT"])
    repository = ProjectOriginRepository(source / "data" / "atom.db",
                                         first_port=first, last_port=last)
    ingress = IpIngressConfig(publication["ATOM_PUBLIC_IP"],
                              publication["ATOM_PREVIEW_UPSTREAM"],
                              publication["ATOM_PUBLIC_UPSTREAM"],
                              publication["ATOM_ACME_DIRECTORY"])
    return IpIngressController(repository, ingress,
        source / "caddy" / "Caddyfile.base",
        source / "caddy" / "Caddyfile",
        DockerCaddy("atom-tls", "/etc/caddy/Caddyfile"))


def _receipt(captured: ip_forward_capture.CapturedGeneration) -> dict[str, object]:
    return {"backupDirectory": str(captured.backup),
            "candidateDirectory": str(captured.candidate),
            "manifestSha256": captured.manifest_sha256,
            "caddySha256": captured.caddy_sha256,
            "cosInventorySha256": captured.cos_inventory_sha256,
            "artifactCount": captured.artifact_count,
            "originCount": captured.origin_count}


def _recover_pre_exposure(*, config: protected_cutover.CutoverConfig,
                          stopped: ip_forward_writers.StoppedWriters | None,
                          controller: IpIngressController, original_base: bytes,
                          journal: ip_forward_journal.ForwardJournal,
                          active: dict[str, object], publication_file: Path,
                          revision: str) -> None:
    """Restore source IDs and strict-TLS routes while the host lock is held."""
    try:
        if stopped is not None:
            ip_forward_writers.resume(config, stopped)
        controller.transition_base(original_base, maintenance=False)
        ip_forward_preflight._inspect_locked(
            config=config, publication_file=publication_file, revision=revision)
        journal.advance("source_restored", evidence={"sourceIdsChecked": True,
                                                    "normalIngressProbed": True})
    except BaseException as exc:
        # Preserve the intent phase and exact identity for an operator/crash
        # recovery command. Never claim a source restore from partial checks.
        raise StageError("forward_source_recovery_failed") from exc


def stage_locked(*, config: protected_cutover.CutoverConfig,
                 publication_file: Path, revision: str,
                 successor_source: Path, successor_revision: str,
                 successor_image: str) -> ForwardStage:
    """Enter maintenance, exclude five writers and capture a COS-bound pair.

    The caller MUST already hold ``protected_cutover.host_lock()`` and must
    keep it held after return. A crash requires journal-guided reconciliation;
    an ordinary exception before exposure attempts same-lock source recovery.
    """
    active = ip_forward_preflight._inspect_locked(
        config=config, publication_file=publication_file, revision=revision,
        successor_source=successor_source,
        successor_revision=successor_revision, successor_image=successor_image)
    publication = ip_forward_preflight._publication(
        publication_file, config, active["imageId"])
    source = Path(active["candidateDirectory"])
    routes = ip_forward_preflight._active_routes(
        source / "data" / "atom.db", int(publication["ATOM_FIRST_PORT"]),
        int(publication["ATOM_LAST_PORT"]))
    controller = _controller(config=config, publication=publication,
                             source=source)
    identity_path = ip_forward_identity.capture(
        config, active, successor_revision, successor_image)
    journal = ip_forward_journal.ForwardJournal(config, successor_revision)
    try:
        journal.begin()
    except BaseException:
        # There has been no ingress/container mutation. Retain the identity
        # receipt for audit; a duplicate invocation must not overwrite it.
        raise
    original_base = ip_forward_identity.caddy_bytes(
        ip_forward_identity.read(identity_path, config=config,
                                 successor_revision=successor_revision), "base")
    stopped = None
    try:
        journal.advance("maintenance_intent")
        maintenance = ip_cutover_apply._maintenance_caddyfile(
            publication["ATOM_PUBLIC_IP"], publication["ATOM_ACME_DIRECTORY"])
        caddy_digest = controller.transition_base(maintenance, maintenance=True)
        ip_cutover_apply._maintenance_probe(publication["ATOM_PUBLIC_IP"])
        journal.advance("maintenance_verified",
                        evidence={"caddySha256": caddy_digest})
        journal.advance("writers_intent")
        stopped = ip_forward_writers.stop(config, active["containerIds"], source)
        journal.advance("writers_stopped")
        captured = ip_forward_capture.capture(
            config=config, active=active, publication=publication,
            stopped=stopped, routes=routes,
            successor_revision=successor_revision)
        journal.advance("captured", capture=_receipt(captured))
        return ForwardStage(active, publication, routes, stopped, captured,
                            journal, controller)
    except BaseException as failure:
        _recover_pre_exposure(config=config, stopped=stopped,
            controller=controller, original_base=original_base,
            journal=journal, active=active,
            publication_file=publication_file, revision=revision)
        raise StageError("forward_stage_failed") from failure
