"""Single-lock ordinary forward deployment from the active schema-18 state.

This remains an internal entry point until journal-guided crash recovery and
real exact-image drills are complete. Never invoke it on production alone.
"""

from __future__ import annotations

from pathlib import Path

import ip_forward_candidate
import ip_forward_exposure
import ip_forward_hold
import ip_forward_identity
import ip_forward_stage
import ip_forward_start
import protected_cutover


class TransactionError(RuntimeError):
    """Credential-free forward deployment error."""


def _restore_unexposed(*, config: protected_cutover.CutoverConfig,
                       stage: ip_forward_stage.ForwardStage,
                       prepared: ip_forward_candidate.PreparedCandidate,
                       publication_file: Path,
                       successor_revision: str,
                       successor_image: str) -> None:
    """Reconcile a failed pre-exposure phase without guessing container IDs."""
    phase = stage.journal.read()["phase"]
    if phase == "source_restored":
        return
    identity = ip_forward_identity.read(
        stage.journal.identity_path, config=config,
        successor_revision=successor_revision)
    if phase == "captured":
        ip_forward_stage._recover_pre_exposure(
            config=config, stopped=stage.stopped,
            controller=stage.controller,
            original_base=ip_forward_identity.caddy_bytes(identity, "base"),
            journal=stage.journal, active=stage.active,
            publication_file=publication_file,
            revision=identity["sourceRevision"])
        return
    if phase in ("candidate_intent", "candidate_ready"):
        ip_forward_start._cleanup_candidate(
            config=config, prepared=prepared, image=successor_image,
            project=ip_forward_start._project(successor_revision),
            publication=stage.publication,
            source_ids=identity["containerIds"])
        ip_forward_hold.restore(
            config=config, stage=stage, identity=identity,
            publication_file=publication_file)
        return
    raise TransactionError("forward_unexposed_recovery_refused")


def run_locked(*, config: protected_cutover.CutoverConfig,
               publication_file: Path, source_revision: str,
               successor_source: Path, successor_revision: str,
               successor_image: str) -> dict[str, str]:
    """Run every ordinary phase while the caller retains the host lock."""
    stage = ip_forward_stage.stage_locked(
        config=config, publication_file=publication_file,
        revision=source_revision, successor_source=successor_source,
        successor_revision=successor_revision,
        successor_image=successor_image)
    try:
        prepared = ip_forward_candidate.prepare(
            config=config, stage=stage, successor_source=successor_source,
            successor_revision=successor_revision,
            successor_image=successor_image)
    except BaseException as failure:
        try:
            identity = ip_forward_identity.read(
                stage.journal.identity_path, config=config,
                successor_revision=successor_revision)
            ip_forward_stage._recover_pre_exposure(
                config=config, stopped=stage.stopped,
                controller=stage.controller,
                original_base=ip_forward_identity.caddy_bytes(identity, "base"),
                journal=stage.journal, active=stage.active,
                publication_file=publication_file,
                revision=source_revision)
        except BaseException as recovery_failure:
            raise TransactionError("forward_preparation_recovery_failed") \
                from recovery_failure
        raise TransactionError("forward_preparation_failed") from failure
    try:
        held = ip_forward_hold.hold(
            config=config, stage=stage, prepared=prepared,
            successor_revision=successor_revision,
            publication_file=publication_file)
    except BaseException as failure:
        try:
            _restore_unexposed(
                config=config, stage=stage, prepared=prepared,
                publication_file=publication_file,
                successor_revision=successor_revision,
                successor_image=successor_image)
        except BaseException as recovery_failure:
            raise TransactionError("forward_handoff_recovery_failed") \
                from recovery_failure
        raise TransactionError("forward_handoff_failed") from failure
    try:
        started = ip_forward_start.start(
            config=config, stage=stage, prepared=prepared, held=held,
            successor_source=successor_source,
            successor_revision=successor_revision,
            successor_image=successor_image,
            publication_file=publication_file)
    except BaseException as failure:
        try:
            _restore_unexposed(
                config=config, stage=stage, prepared=prepared,
                publication_file=publication_file,
                successor_revision=successor_revision,
                successor_image=successor_image)
        except BaseException as recovery_failure:
            raise TransactionError("forward_start_recovery_failed") \
                from recovery_failure
        raise TransactionError("forward_start_failed") from failure
    try:
        ip_forward_exposure.expose(
            config=config, stage=stage, prepared=prepared, held=held,
            started=started, successor_revision=successor_revision,
            successor_image=successor_image,
            publication_file=publication_file)
    except BaseException as failure:
        try:
            if stage.journal.read()["phase"] == "candidate_ready":
                _restore_unexposed(
                    config=config, stage=stage, prepared=prepared,
                    publication_file=publication_file,
                    successor_revision=successor_revision,
                    successor_image=successor_image)
        except BaseException as recovery_failure:
            raise TransactionError("forward_exposure_recovery_failed") \
                from recovery_failure
        raise TransactionError("forward_exposure_failed") from failure
    return {"status": "awaiting_acceptance", "sourceRevision": source_revision,
            "successorRevision": successor_revision,
            "sourceImageId": stage.active["imageId"],
            "successorImageId": successor_image,
            "candidateDirectory": str(prepared.directory),
            "backupDirectory": str(stage.captured.backup)}


def run(*, config_file: Path, publication_file: Path,
        source_revision: str, successor_source: Path,
        successor_revision: str, successor_image: str) -> dict[str, str]:
    """Acquire one exclusive host lock around every checked-to-mutated step."""
    config = protected_cutover.load_config(config_file)
    with protected_cutover.host_lock():
        return run_locked(
            config=config, publication_file=publication_file,
            source_revision=source_revision,
            successor_source=successor_source,
            successor_revision=successor_revision,
            successor_image=successor_image)
