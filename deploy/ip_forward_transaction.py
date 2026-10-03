"""Single-lock, phase-recorded forward deployment from active schema-18 data.

This command requires an exact clean Git revision and immutable image ID.
Read-only preflight, phase journaling and a verified paired backup are part of
the host-locked transaction; crash recovery and acceptance are separate steps.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import ip_forward_candidate
import ip_forward_capture
import ip_forward_exposure
import ip_forward_hold
import ip_forward_identity
import ip_forward_journal
import ip_forward_preflight
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
    if phase == "candidate_ready":
        candidate = stage.journal.read()["candidate"]
        ip_forward_exposure.recover_after_exposure(
            config=config, stage=stage, prepared=prepared,
            held=ip_forward_hold.HeldSource(
                identity["containerIds"], identity["heldNames"]),
            started=ip_forward_start.StartedCandidate(
                candidate["containerIds"],
                config.state_dir / (successor_revision + ".forward-baseline.json"),
                candidate["baselineSha256"], candidate["caddySha256"]),
            successor_revision=successor_revision,
            successor_image=successor_image,
            publication_file=publication_file)
        return
    if phase == "candidate_intent":
        ip_forward_start._fence_partial_candidate(
            config=config, stage=stage, prepared=prepared,
            successor_revision=successor_revision,
            successor_image=successor_image,
            source_ids=identity["containerIds"])
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
        if (isinstance(failure, ip_forward_hold.HoldError)
                and str(failure) == "forward_held_source_recovery_failed"):
            raise TransactionError("forward_handoff_recovery_failed") from failure
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
        if (isinstance(failure, ip_forward_start.StartError)
                and str(failure) == "forward_candidate_recovery_failed"):
            raise TransactionError("forward_start_recovery_failed") from failure
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
        if (isinstance(failure, ip_forward_exposure.ExposureError)
                and str(failure) == "forward_exposure_recovery_failed"):
            raise TransactionError("forward_exposure_recovery_failed") from failure
        try:
            if stage.journal.read()["phase"] == "candidate_ready":
                ip_forward_exposure.recover_after_exposure(
                    config=config, stage=stage, prepared=prepared, held=held,
                    started=started, successor_revision=successor_revision,
                    successor_image=successor_image,
                    publication_file=publication_file)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--publication-file", required=True, type=Path)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--successor-source", required=True, type=Path)
    parser.add_argument("--successor-revision", required=True)
    parser.add_argument("--successor-image", required=True)
    args = parser.parse_args(argv)
    try:
        result = run(
            config_file=args.config,
            publication_file=args.publication_file,
            source_revision=args.source_revision,
            successor_source=args.successor_source,
            successor_revision=args.successor_revision,
            successor_image=args.successor_image)
    except (TransactionError, protected_cutover.CutoverError,
            ip_forward_preflight.ForwardPreflightError,
            ip_forward_journal.JournalError,
            ip_forward_identity.IdentityError,
            ip_forward_stage.StageError,
            ip_forward_capture.CaptureError,
            ip_forward_candidate.CandidateError,
            ip_forward_hold.HoldError,
            ip_forward_start.StartError,
            ip_forward_exposure.ExposureError) as exc:
        parser.exit(2, str(exc) + "\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
