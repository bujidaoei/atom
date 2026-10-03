"""Recover one interrupted forward transaction before ingress reconciliation.

The root-owned origin timer calls this bounded preflight before its normal
reconcile action. A healthy ``awaiting_acceptance`` generation is serving,
not an interrupted transaction. All decisions and recovery share the host
deployment lock; ambiguous or orphaned receipts fail closed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import stat

import candidate_write_fence
import ip_forward_exposure
import ip_forward_identity
import ip_forward_journal
import ip_forward_preflight
import ip_forward_recovery
import ip_forward_stage
import ip_forward_start
import ip_forward_writers
import protected_cutover


class AutoRecoveryError(RuntimeError):
    """Stable, credential-free refusal for ambiguous host state."""


SUFFIX = ".forward-phase.json"
IDENTITY_SUFFIX = ".forward.json"
SERVING_PHASES = frozenset({"awaiting_acceptance", "source_restored",
                            "successor_retained", "accepted"})
MAX_JOURNALS = 256


def _inventory(config: protected_cutover.CutoverConfig) -> dict[str, str]:
    """Validate every known forward identity and return its durable phase."""
    ip_forward_journal._private_directory(config.state_dir)
    try:
        phase_paths = tuple(config.state_dir.glob("*" + SUFFIX))
        identity_paths = tuple(config.state_dir.glob("*" + IDENTITY_SUFFIX))
    except OSError as exc:
        raise AutoRecoveryError("forward_inventory_unavailable") from exc
    if len(phase_paths) > MAX_JOURNALS or len(identity_paths) > MAX_JOURNALS:
        raise AutoRecoveryError("forward_inventory_unbounded")
    phases: dict[str, str] = {}
    for path in phase_paths:
        revision = path.name.removesuffix(SUFFIX)
        if (path.name != revision + SUFFIX
                or protected_cutover.REVISION.fullmatch(revision) is None):
            raise AutoRecoveryError("forward_inventory_invalid")
        record = ip_forward_journal.ForwardJournal(config, revision).read()
        if record is None:
            raise AutoRecoveryError("forward_receipt_missing")
        phases[revision] = record["phase"]
    for path in identity_paths:
        revision = path.name.removesuffix(IDENTITY_SUFFIX)
        if (path.name != revision + IDENTITY_SUFFIX
                or protected_cutover.REVISION.fullmatch(revision) is None
                or revision not in phases):
            raise AutoRecoveryError("forward_orphan_identity")
        try:
            info = path.lstat()
        except OSError as exc:
            raise AutoRecoveryError("forward_identity_unavailable") from exc
        if not stat.S_ISREG(info.st_mode) or path.is_symlink():
            raise AutoRecoveryError("forward_identity_invalid")
        ip_forward_identity.read(path, config=config,
                                 successor_revision=revision)
    return phases


def _interrupted_revision(phases: dict[str, str]) -> str | None:
    interrupted = [revision for revision, phase in phases.items()
                   if phase not in SERVING_PHASES]
    if len(interrupted) > 1:
        raise AutoRecoveryError("multiple_interrupted_forward_transactions")
    return interrupted[0] if interrupted else None


def recover_locked(*, config: protected_cutover.CutoverConfig,
                   publication_file: Path) -> dict[str, str]:
    """Caller holds the shared host lock through inventory and transition."""
    if not publication_file.is_absolute():
        raise AutoRecoveryError("invalid_publication_file")
    revision = _interrupted_revision(_inventory(config))
    if revision is None:
        return {"status": "no_recovery_needed"}
    try:
        outcome = ip_forward_recovery.recover_locked(
            config=config, publication_file=publication_file,
            successor_revision=revision)
    except (ip_forward_recovery.RecoveryError,
            protected_cutover.CutoverError,
            ip_forward_journal.JournalError,
            ip_forward_identity.IdentityError,
            ip_forward_preflight.ForwardPreflightError,
            ip_forward_exposure.ExposureError,
            ip_forward_stage.StageError,
            ip_forward_start.StartError,
            ip_forward_writers.WriterError,
            candidate_write_fence.FenceError) as exc:
        raise AutoRecoveryError("forward_auto_recovery_failed:" + str(exc)) from exc
    if outcome not in {"source_restored", "successor_retained"}:
        raise AutoRecoveryError("forward_auto_recovery_not_terminal")
    return {"status": outcome, "revision": revision}


def recover(*, config_file: Path,
            publication_file: Path) -> dict[str, str]:
    config = protected_cutover.load_config(config_file)
    with protected_cutover.host_lock():
        return recover_locked(config=config, publication_file=publication_file)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--publication-file", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = recover(config_file=args.config,
                         publication_file=args.publication_file)
    except protected_cutover.CutoverError as exc:
        if str(exc) == "cutover_lock_busy":
            return 0  # The active transaction owns the lock; retry on next tick.
        parser.exit(2, str(exc) + "\n")
    except (AutoRecoveryError, ip_forward_journal.JournalError,
            ip_forward_identity.IdentityError) as exc:
        parser.exit(2, str(exc) + "\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
