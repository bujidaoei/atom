"""Reconcile newly reserved project origins without exposing Docker to the API.

Run as a bounded host service. A serving generation and every Docker identity
must validate under the same deployment lock used by cutovers. Any interrupted
forward transaction prevents normal-route reconciliation.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import ip_forward_journal
import ip_forward_identity
import ip_forward_preflight
import ip_forward_stage
import protected_cutover
from app.ip_ingress import IngressError


class OriginReconcileError(RuntimeError):
    """Credential-free refusal code for an unsafe reconciliation."""


SERVING_PHASES = frozenset({"awaiting_acceptance", "successor_retained",
                            "source_restored", "accepted"})


def _no_interrupted_forward(config: protected_cutover.CutoverConfig) -> None:
    try:
        paths = tuple(config.state_dir.glob("*.forward-phase.json"))
    except OSError as exc:
        raise OriginReconcileError("forward_journal_inventory_unavailable") from exc
    for path in paths:
        revision = path.name.removesuffix(".forward-phase.json")
        if (path.name != revision + ".forward-phase.json"
                or protected_cutover.REVISION.fullmatch(revision) is None):
            raise OriginReconcileError("forward_journal_inventory_invalid")
        record = ip_forward_journal.ForwardJournal(config, revision).read()
        if record is None or record["phase"] not in SERVING_PHASES:
            raise OriginReconcileError("forward_transaction_incomplete")
    # An identity receipt without a phase receipt can mean a crash between
    # sealing identities and recording the first intent. Fail closed.
    for path in config.state_dir.glob("*.forward.json"):
        revision = path.name.removesuffix(".forward.json")
        if (protected_cutover.REVISION.fullmatch(revision) is None
                or not (config.state_dir /
                        (revision + ".forward-phase.json")).is_file()):
            raise OriginReconcileError("forward_orphan_identity")


def reconcile_locked(*, config: protected_cutover.CutoverConfig,
                     publication_file: Path) -> dict[str, object]:
    """Caller holds protected_cutover.host_lock for inspection and reload."""
    _no_interrupted_forward(config)
    api = protected_cutover._inspect(config.docker, "container", config.api)
    if (api.get("Name") != "/" + config.api
            or api.get("State", {}).get("Running") is not True):
        raise OriginReconcileError("active_api_identity_unavailable")
    image = protected_cutover._inspect(config.docker, "image", api.get("Image", ""))
    revision = image.get("Config", {}).get("Labels", {}).get("atom.revision")
    if (protected_cutover.REVISION.fullmatch(revision or "") is None
            or image.get("Id") != api.get("Image")):
        raise OriginReconcileError("active_image_revision_unavailable")
    active = ip_forward_preflight._inspect_locked(
        config=config, publication_file=publication_file, revision=revision,
        allow_ingress_drift=True, allow_live_activity=True)
    if not active["ingressDrift"]:
        return {"status": "origin_ingress_current", "revision": revision,
                "originCount": active["activeOriginCount"]}
    publication = ip_forward_preflight._publication(
        publication_file, config, active["imageId"],
        require_template_image=False)
    controller = ip_forward_stage._controller(
        config=config, publication=publication,
        source=Path(active["candidateDirectory"]))
    digest = controller.reconcile()
    verified = ip_forward_preflight._inspect_locked(
        config=config, publication_file=publication_file, revision=revision,
        allow_live_activity=True)
    if (verified["containerIds"] != active["containerIds"]
            or verified["caddySha256"] != digest):
        raise OriginReconcileError("origin_reconcile_verification_failed")
    return {"status": "origin_ingress_reconciled", "revision": revision,
            "originCount": verified["activeOriginCount"], "caddySha256": digest}


def reconcile(*, config_file: Path, publication_file: Path) -> dict[str, object]:
    config = protected_cutover.load_config(config_file)
    with protected_cutover.host_lock():
        return reconcile_locked(config=config, publication_file=publication_file)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--publication-file", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = reconcile(config_file=args.config,
                           publication_file=args.publication_file)
    except protected_cutover.CutoverError as exc:
        if str(exc) == "cutover_lock_busy":
            return 0
        parser.exit(2, str(exc) + "\n")
    except (OriginReconcileError, ip_forward_preflight.ForwardPreflightError,
            ip_forward_journal.JournalError, ip_forward_identity.IdentityError,
            IngressError) as exc:
        parser.exit(2, str(exc) + "\n")
    if result["status"] == "origin_ingress_reconciled":
        print(result["status"], result["originCount"], result["caddySha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
