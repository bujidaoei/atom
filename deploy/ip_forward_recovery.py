"""Reconcile an interrupted forward transaction from its durable receipt.

The operator entry point dispatches under one host lock. Each phase-specific
continuation verifies exact service identities and the required write fence;
the phase name alone never authorizes restoring an older data generation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import hashlib
import stat

import candidate_write_fence
import ip_forward_candidate
import ip_forward_capture
import ip_forward_exposure
import ip_forward_hold
import ip_forward_identity
import ip_forward_journal
import ip_forward_preflight
import ip_forward_stage
import ip_forward_start
import ip_forward_writers
import protected_cutover


PRE_HANDOFF = frozenset({
    "prepared", "maintenance_intent", "maintenance_verified",
    "writers_intent", "writers_stopped", "captured",
})


class RecoveryError(RuntimeError):
    """Stable, credential-free recovery refusal."""


def recover_pre_handoff_locked(*, config: protected_cutover.CutoverConfig,
                               publication_file: Path,
                               successor_revision: str) -> str:
    """Restore the exact source generation while the host lock is retained.

    An interrupted writer stop may have stopped any prefix of the five IDs.
    The journal must be valid, every source ID must still hold its canonical
    name, and the original Caddy must still be running. The final live
    preflight and journal terminal receipt are written by the shared source
    recovery path only after routes and all writers are healthy.
    """
    if not publication_file.is_absolute():
        raise RecoveryError("invalid_forward_recovery_input")
    journal = ip_forward_journal.ForwardJournal(config, successor_revision)
    record = journal.read()
    if record is None or record["phase"] not in PRE_HANDOFF:
        raise RecoveryError("forward_recovery_phase_refused")
    identity = ip_forward_identity.read(
        journal.identity_path, config=config,
        successor_revision=successor_revision)
    source_ids = identity["containerIds"]
    for role in ip_forward_identity.ROLES:
        expected_name = ip_forward_identity._name(config, role)
        try:
            item = protected_cutover._inspect(config.docker, "container",
                                              source_ids[role])
        except protected_cutover.CutoverError as exc:
            raise RecoveryError("forward_source_identity_unavailable") from exc
        if (item.get("Id") != source_ids[role]
                or item.get("Name") != "/" + expected_name
                or (role == "caddy" and item.get("State", {}).get("Running")
                    is not True)):
            raise RecoveryError("forward_source_identity_changed")
    publication = ip_forward_preflight._publication(
        publication_file, config, identity["sourceImageId"],
        require_template_image=False)
    controller = ip_forward_stage._controller(
        config=config, publication=publication,
        source=Path(identity["sourceDirectory"]))
    stopped = ip_forward_writers.StoppedWriters({
        role: source_ids[role] for role in ip_forward_writers.STOP_ORDER})
    ip_forward_stage._recover_pre_exposure(
        config=config, stopped=stopped, controller=controller,
        original_base=ip_forward_identity.caddy_bytes(identity, "base"),
        journal=journal, active={"containerIds": source_ids},
        publication_file=publication_file,
        revision=identity["sourceRevision"])
    return "source_restored"


def _candidate_caddy_digest(candidate: Path, expected: str | set[str]) -> None:
    ip_forward_candidate._private_directory(candidate)
    ip_forward_candidate._private_directory(candidate / "caddy")
    caddy_file = candidate / "caddy" / "Caddyfile"
    try:
        info = caddy_file.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or stat.S_IMODE(info.st_mode) != 0o600
                or hashlib.sha256(caddy_file.read_bytes()).hexdigest()
                not in ({expected} if type(expected) is str else expected)):
            raise RecoveryError("forward_candidate_caddy_changed")
    except OSError as exc:
        raise RecoveryError("forward_candidate_caddy_unavailable") from exc


def _rebuild_context(*, config: protected_cutover.CutoverConfig,
                     publication_file: Path, successor_revision: str,
                     allowed_phases: set[str]) -> tuple[dict, dict,
                                                        ip_forward_stage.ForwardStage,
                                                        ip_forward_candidate.PreparedCandidate]:
    """Recreate validated recovery inputs without replaying any deploy phase."""
    if not publication_file.is_absolute():
        raise RecoveryError("invalid_forward_recovery_input")
    journal = ip_forward_journal.ForwardJournal(config, successor_revision)
    record = journal.read()
    if record is None or record["phase"] not in allowed_phases:
        raise RecoveryError("forward_recovery_phase_refused")
    identity = ip_forward_identity.read(
        journal.identity_path, config=config,
        successor_revision=successor_revision)
    publication = ip_forward_preflight._publication(
        publication_file, config, identity["sourceImageId"],
        require_template_image=False)
    source = Path(identity["sourceDirectory"])
    candidate = Path(identity["candidateDirectory"])
    capture = record["capture"]
    if capture is None:
        raise RecoveryError("forward_capture_receipt_missing")
    allowed_caddy = {capture["caddySha256"]}
    if record["phase"] in {"exposure_intent", "awaiting_acceptance",
                           "source_restore_intent"}:
        allowed_caddy.add(identity["caddy"]["active"]["sha256"])
    _candidate_caddy_digest(candidate, allowed_caddy)
    prepared = ip_forward_candidate.PreparedCandidate(
        candidate, candidate / "compose.env",
        candidate / "private-env" / "api.env",
        candidate / "private-env" / "broker.env",
        identity["serviceIps"]["caddy"], identity["serviceIps"],
        capture["caddySha256"])
    routes = ip_forward_preflight._active_routes(
        source / "data" / "atom.db",
        int(publication["ATOM_FIRST_PORT"]),
        int(publication["ATOM_LAST_PORT"]))
    stage = ip_forward_stage.ForwardStage(
        {"containerIds": identity["containerIds"],
         "candidateDirectory": str(source),
         "imageId": identity["sourceImageId"]},
        publication, routes,
        ip_forward_writers.StoppedWriters({
            role: identity["containerIds"][role]
            for role in ip_forward_writers.STOP_ORDER}),
        ip_forward_capture.CapturedGeneration(
            Path(capture["backupDirectory"]), candidate,
            capture["manifestSha256"], capture["caddySha256"],
            capture["artifactCount"], capture["originCount"],
            capture["cosInventorySha256"]),
        journal,
        ip_forward_stage._controller(config=config,
                                     publication=publication, source=source))
    return record, identity, stage, prepared


def recover_partial_handoff_locked(*, config: protected_cutover.CutoverConfig,
                                   publication_file: Path,
                                   successor_revision: str) -> str:
    """Fence a partially started successor before restoring held source IDs."""
    _record, identity, stage, prepared = _rebuild_context(
        config=config, publication_file=publication_file,
        successor_revision=successor_revision,
        allowed_phases={"candidate_intent"})
    ip_forward_start._fence_partial_candidate(
        config=config, stage=stage, prepared=prepared,
        successor_revision=successor_revision,
        successor_image=identity["successorImageId"],
        source_ids=identity["containerIds"])
    ip_forward_start._cleanup_candidate(
        config=config, prepared=prepared,
        image=identity["successorImageId"],
        project=ip_forward_start._project(successor_revision),
        publication=stage.publication,
        source_ids=identity["containerIds"])
    ip_forward_hold.restore(config=config, stage=stage,
                            identity=identity,
                            publication_file=publication_file,
                            write_fence_unchanged=True)
    return "source_restored"


def recover_ready_or_exposed_locked(*,
        config: protected_cutover.CutoverConfig,
        publication_file: Path, successor_revision: str) -> str:
    """Reconcile a fully identified running successor by its sealed write fence."""
    record, identity, stage, prepared = _rebuild_context(
        config=config, publication_file=publication_file,
        successor_revision=successor_revision,
        allowed_phases={"candidate_ready", "exposure_intent",
                        "awaiting_acceptance"})
    candidate = record["candidate"]
    if candidate is None:
        raise RecoveryError("forward_candidate_receipt_missing")
    held = ip_forward_hold.HeldSource(identity["containerIds"],
                                     identity["heldNames"])
    started = ip_forward_start.StartedCandidate(
        candidate["containerIds"],
        config.state_dir / (successor_revision + ".forward-baseline.json"),
        candidate["baselineSha256"], candidate["caddySha256"])
    return ip_forward_exposure.recover_after_exposure(
        config=config, stage=stage, prepared=prepared, held=held,
        started=started, successor_revision=successor_revision,
        successor_image=identity["successorImageId"],
        publication_file=publication_file)


def finish_source_restore_locked(*, config: protected_cutover.CutoverConfig,
                                 publication_file: Path,
                                 successor_revision: str) -> str:
    """Finish a durably authorized source restore after cleanup was interrupted."""
    record, identity, stage, prepared = _rebuild_context(
        config=config, publication_file=publication_file,
        successor_revision=successor_revision,
        allowed_phases={"source_restore_intent"})
    candidate = record["candidate"]
    if candidate is None:
        raise RecoveryError("forward_candidate_receipt_missing")
    for role in ip_forward_identity.ROLES:
        item = ip_forward_start._current(config, role)
        if item is None or item.get("Id") == identity["containerIds"][role]:
            continue
        if item.get("Id") != candidate["containerIds"][role]:
            raise RecoveryError("forward_recovery_unknown_container")
        if (role != "caddy"
                and item.get("State", {}).get("Running") is not False):
            raise RecoveryError("forward_recovery_writer_restarted")
    try:
        unchanged = candidate_write_fence.compare_baseline(
            config.state_dir / (successor_revision + ".forward-baseline.json"),
            candidate_directory=prepared.directory,
            revision=successor_revision,
            candidate_image=identity["successorImageId"],
            expected_digest=candidate["baselineSha256"])
    except candidate_write_fence.FenceError as exc:
        raise RecoveryError("forward_restore_fence_unverified") from exc
    if not unchanged:
        raise RecoveryError("forward_restore_candidate_changed")
    ip_forward_start._cleanup_candidate(
        config=config, prepared=prepared,
        image=identity["successorImageId"],
        project=ip_forward_start._project(successor_revision),
        publication=stage.publication,
        source_ids=identity["containerIds"])
    ip_forward_hold.restore(
        config=config, stage=stage, identity=identity,
        publication_file=publication_file, write_fence_unchanged=True)
    return "source_restored"


def recover_pre_handoff(*, config_file: Path, publication_file: Path,
                        successor_revision: str) -> str:
    """Keep receipt inspection and all source transitions under one lock."""
    config = protected_cutover.load_config(config_file)
    with protected_cutover.host_lock():
        return recover_pre_handoff_locked(
            config=config, publication_file=publication_file,
            successor_revision=successor_revision)


def recover_partial_handoff(*, config_file: Path, publication_file: Path,
                            successor_revision: str) -> str:
    """Hold the host lock while fencing and reconciling a partial handoff."""
    config = protected_cutover.load_config(config_file)
    with protected_cutover.host_lock():
        return recover_partial_handoff_locked(
            config=config, publication_file=publication_file,
            successor_revision=successor_revision)


def recover_ready_or_exposed(*, config_file: Path,
                             publication_file: Path,
                             successor_revision: str) -> str:
    """Retain one host lock across exact-ID successor recovery."""
    config = protected_cutover.load_config(config_file)
    with protected_cutover.host_lock():
        return recover_ready_or_exposed_locked(
            config=config, publication_file=publication_file,
            successor_revision=successor_revision)


def finish_source_restore(*, config_file: Path,
                          publication_file: Path,
                          successor_revision: str) -> str:
    """Hold one lock while completing a previously sealed restore decision."""
    config = protected_cutover.load_config(config_file)
    with protected_cutover.host_lock():
        return finish_source_restore_locked(
            config=config, publication_file=publication_file,
            successor_revision=successor_revision)


def recover_locked(*, config: protected_cutover.CutoverConfig,
                   publication_file: Path,
                   successor_revision: str) -> str:
    """Dispatch by the fsynced phase while the caller holds the host lock."""
    if not publication_file.is_absolute():
        raise RecoveryError("invalid_forward_recovery_input")
    journal = ip_forward_journal.ForwardJournal(config, successor_revision)
    record = journal.read()
    if record is None:
        raise RecoveryError("forward_recovery_receipt_missing")
    phase = record["phase"]
    if phase in PRE_HANDOFF:
        return recover_pre_handoff_locked(
            config=config, publication_file=publication_file,
            successor_revision=successor_revision)
    if phase == "candidate_intent":
        return recover_partial_handoff_locked(
            config=config, publication_file=publication_file,
            successor_revision=successor_revision)
    if phase in {"candidate_ready", "exposure_intent",
                 "awaiting_acceptance"}:
        return recover_ready_or_exposed_locked(
            config=config, publication_file=publication_file,
            successor_revision=successor_revision)
    if phase == "source_restore_intent":
        return finish_source_restore_locked(
            config=config, publication_file=publication_file,
            successor_revision=successor_revision)
    # A terminal receipt is not a reason to repeat a container transition.
    # Verify its claimed serving generation against all six live IDs instead.
    if phase in {"source_restored", "successor_retained", "accepted"}:
        identity = ip_forward_identity.read(
            journal.identity_path, config=config,
            successor_revision=successor_revision)
        revision = (identity["sourceRevision"] if phase == "source_restored"
                    else successor_revision)
        ip_forward_preflight._inspect_locked(
            config=config, publication_file=publication_file,
            revision=revision)
        return phase
    raise RecoveryError("forward_recovery_phase_refused")


def recover(*, config_file: Path, publication_file: Path,
            successor_revision: str) -> str:
    """Keep phase selection, reconciliation and final checks under one lock."""
    config = protected_cutover.load_config(config_file)
    with protected_cutover.host_lock():
        return recover_locked(
            config=config, publication_file=publication_file,
            successor_revision=successor_revision)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--publication-file", required=True, type=Path)
    parser.add_argument("--successor-revision", required=True)
    args = parser.parse_args(argv)
    try:
        outcome = recover(
            config_file=args.config, publication_file=args.publication_file,
            successor_revision=args.successor_revision)
    except (RecoveryError, protected_cutover.CutoverError,
            ip_forward_journal.JournalError,
            ip_forward_preflight.ForwardPreflightError,
            ip_forward_exposure.ExposureError,
            ip_forward_hold.HoldError,
            ip_forward_start.StartError,
            ip_forward_stage.StageError,
            ip_forward_writers.WriterError,
            candidate_write_fence.FenceError) as exc:
        parser.exit(2, str(exc) + "\n")
    print(json.dumps({"status": outcome}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
