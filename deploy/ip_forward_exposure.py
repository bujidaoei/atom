"""Same-lock successor exposure and write-aware ordinary failure recovery.

No CLI is exposed until crash reconciliation can reconstruct this transaction.
The caller keeps the host cutover lock from source preflight through outcome.
"""

from __future__ import annotations

from pathlib import Path

import candidate_write_fence
import ip_cutover_apply
import ip_cutover_rollback
import ip_forward_candidate
import ip_forward_hold
import ip_forward_identity
import ip_forward_preflight
import ip_forward_stage
import ip_forward_start
import ip_forward_writers
import protected_cutover


class ExposureError(RuntimeError):
    """Credential-free forward exposure or recovery error."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ExposureError(code)


def _identity(*, config: protected_cutover.CutoverConfig,
              stage: ip_forward_stage.ForwardStage,
              prepared: ip_forward_candidate.PreparedCandidate,
              held: ip_forward_hold.HeldSource,
              started: ip_forward_start.StartedCandidate,
              successor_revision: str, successor_image: str,
              verify_baseline: bool = True) -> dict:
    receipt = ip_forward_identity.read(
        stage.journal.identity_path, config=config,
        successor_revision=successor_revision)
    candidate = stage.journal.read()["candidate"]
    _require(candidate is not None
             and receipt["containerIds"] == held.ids
             and receipt["heldNames"] == held.names
             and receipt["serviceIps"] == prepared.service_ips
             and receipt["candidateDirectory"] == str(prepared.directory)
             and receipt["successorImageId"] == successor_image
             and candidate["containerIds"] == started.ids
             and candidate["directory"] == str(prepared.directory)
             and candidate["imageId"] == successor_image
             and candidate["baselineSha256"] == started.baseline_sha256
             and candidate["caddySha256"] == started.maintenance_sha256
             and started.baseline_path == config.state_dir / (
                 successor_revision + ".forward-baseline.json"),
             "forward_exposure_identity_mismatch")
    if verify_baseline:
        candidate_write_fence.read_baseline(
            started.baseline_path, candidate_directory=prepared.directory,
            revision=successor_revision, candidate_image=successor_image,
            expected_digest=started.baseline_sha256)
    for role in ip_forward_identity.ROLES:
        ip_forward_hold._inspect(config, held.ids[role], held.names[role],
                                 running=False)
    for role in ip_forward_identity.ROLES:
        item = ip_forward_start._current(config, role)
        _require(item is not None and item.get("Id") == started.ids[role]
                 and item.get("State", {}).get("Running") is True,
                 "forward_exposure_service_changed")
        ip_forward_start._profile(
            config=config, role=role, item=item, image=successor_image,
            prepared=prepared, project=ip_forward_start._project(
                successor_revision), publication=stage.publication)
    _require(ip_forward_preflight._active_routes(
        prepared.directory / "data" / "atom.db",
        int(stage.publication["ATOM_FIRST_PORT"]),
        int(stage.publication["ATOM_LAST_PORT"])) == stage.routes,
        "forward_exposure_origins_changed")
    return receipt


def _candidate_controller(*, config: protected_cutover.CutoverConfig,
                          stage: ip_forward_stage.ForwardStage,
                          prepared: ip_forward_candidate.PreparedCandidate):
    return ip_forward_stage._controller(
        config=config, publication=stage.publication, source=prepared.directory)


def recover_after_exposure(*, config: protected_cutover.CutoverConfig,
                           stage: ip_forward_stage.ForwardStage,
                           prepared: ip_forward_candidate.PreparedCandidate,
                           held: ip_forward_hold.HeldSource,
                           started: ip_forward_start.StartedCandidate,
                           successor_revision: str, successor_image: str,
                           publication_file: Path) -> str:
    """Fence a possibly exposed successor and select the only safe generation."""
    _require(stage.journal.read()["phase"] in (
        "candidate_ready", "exposure_intent", "awaiting_acceptance"),
        "forward_exposure_phase_mismatch")
    receipt = _identity(config=config, stage=stage, prepared=prepared,
        held=held, started=started, successor_revision=successor_revision,
        successor_image=successor_image, verify_baseline=False)
    controller = _candidate_controller(config=config, stage=stage,
                                       prepared=prepared)
    maintenance = ip_cutover_apply._maintenance_caddyfile(
        stage.publication["ATOM_PUBLIC_IP"],
        stage.publication["ATOM_ACME_DIRECTORY"])
    controller.transition_base(maintenance, maintenance=True)
    ip_cutover_apply._maintenance_probe(stage.publication["ATOM_PUBLIC_IP"])
    stopped = ip_forward_writers.stop(config, started.ids, prepared.directory)
    try:
        unchanged = candidate_write_fence.compare_baseline(
            started.baseline_path, candidate_directory=prepared.directory,
            revision=successor_revision, candidate_image=successor_image,
            expected_digest=started.baseline_sha256)
    except candidate_write_fence.FenceError:
        # An unreadable or mismatched receipt cannot authorize old data.
        unchanged = None
    if unchanged:
        ip_forward_start._cleanup_candidate(
            config=config, prepared=prepared, image=successor_image,
            project=ip_forward_start._project(successor_revision),
            publication=stage.publication)
        ip_forward_hold.restore(
            config=config, stage=stage, identity=receipt,
            publication_file=publication_file, write_fence_unchanged=True)
        return "source_restored"
    ip_forward_writers.resume(config, stopped)
    normal = ip_forward_identity.caddy_bytes(receipt, "base")
    controller.transition_base(normal, maintenance=False)
    ip_cutover_rollback._await_console(
        "https://" + stage.publication["ATOM_PUBLIC_IP"] + "/atom/")
    stage.journal.advance("successor_retained", evidence={
        "writeFence": "changed" if unchanged is False else "unverified",
        "successorIdsChecked": True,
        "normalIngressProbed": True})
    return "successor_retained"


def expose(*, config: protected_cutover.CutoverConfig,
           stage: ip_forward_stage.ForwardStage,
           prepared: ip_forward_candidate.PreparedCandidate,
           held: ip_forward_hold.HeldSource,
           started: ip_forward_start.StartedCandidate,
           successor_revision: str, successor_image: str,
           publication_file: Path) -> None:
    """Record exposure intent before opening normal HTTPS routes."""
    _require(stage.journal.read()["phase"] == "candidate_ready"
             and publication_file.is_absolute(),
             "forward_exposure_phase_mismatch")
    receipt = _identity(config=config, stage=stage, prepared=prepared,
        held=held, started=started, successor_revision=successor_revision,
        successor_image=successor_image)
    controller = _candidate_controller(config=config, stage=stage,
                                       prepared=prepared)
    try:
        stage.journal.advance("exposure_intent")
        normal = ip_forward_identity.caddy_bytes(receipt, "base")
        digest = controller.transition_base(normal, maintenance=False)
        ip_cutover_rollback._await_console(
            "https://" + stage.publication["ATOM_PUBLIC_IP"] + "/atom/")
        stage.journal.advance("awaiting_acceptance", evidence={
            "caddySha256": digest, "normalIngressProbed": True})
    except BaseException as failure:
        try:
            recover_after_exposure(
                config=config, stage=stage, prepared=prepared, held=held,
                started=started, successor_revision=successor_revision,
                successor_image=successor_image,
                publication_file=publication_file)
        except BaseException as recovery_failure:
            raise ExposureError("forward_exposure_recovery_failed") from recovery_failure
        raise ExposureError("forward_exposure_failed") from failure
