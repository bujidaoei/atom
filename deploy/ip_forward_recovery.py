"""Reconcile an interrupted forward transaction before source handoff.

This internal entry point covers only durable phases through ``captured``.
Later phases require candidate-ID and write-fence reconciliation, so callers
must never infer that a phase name alone authorizes source restoration.
"""

from __future__ import annotations

from pathlib import Path

import ip_forward_identity
import ip_forward_journal
import ip_forward_preflight
import ip_forward_stage
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
        publication_file, config, identity["sourceImageId"])
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


def recover_pre_handoff(*, config_file: Path, publication_file: Path,
                        successor_revision: str) -> str:
    """Keep receipt inspection and all source transitions under one lock."""
    config = protected_cutover.load_config(config_file)
    with protected_cutover.host_lock():
        return recover_pre_handoff_locked(
            config=config, publication_file=publication_file,
            successor_revision=successor_revision)
