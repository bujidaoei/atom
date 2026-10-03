"""Apply the Atom console-proof redaction policy to live IP ingress logs.

The host-only operator holds the cutover lock, validates the exact serving
generation, and uses the existing atomic ingress controller to validate,
reload, probe, and roll back the Caddy configuration. No API container gets
Docker control.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import ip_caddy_logging
import ip_forward_preflight
import ip_forward_stage
import ip_forward_journal
import ip_forward_identity
import ip_origin_reconcile
import protected_cutover
from app.ip_ingress import IngressError


def _backup_configuration(config: protected_cutover.CutoverConfig,
                          revision: str, base: bytes, active: bytes) -> Path:
    """Seal the two prior root-private ingress files before any reload."""
    digest = hashlib.sha256(base + b"\0" + active).hexdigest()
    receipt = {"revision": revision, "sha256": digest,
               "baseSha256": hashlib.sha256(base).hexdigest(),
               "activeSha256": hashlib.sha256(active).hexdigest()}
    destination = config.backup_root / (
        "ingress-log-pre-" + revision[:12] + "-" + digest[:12])
    if destination.exists():
        try:
            if (destination.is_symlink() or destination.stat().st_uid != 0
                    or (destination.stat().st_mode & 0o777) != 0o700
                    or (destination / "Caddyfile.base").read_bytes() != base
                    or (destination / "Caddyfile").read_bytes() != active
                    or json.loads((destination / "manifest.json").read_text("utf-8"))
                    != receipt):
                raise ip_caddy_logging.IngressLogPolicyError(
                    "ingress_log_backup_mismatch")
        except (OSError, ValueError, UnicodeError):
            raise ip_caddy_logging.IngressLogPolicyError(
                "ingress_log_backup_unavailable") from None
        return destination
    staging = Path(tempfile.mkdtemp(
        prefix="ingress-log-staging-", dir=config.backup_root))
    for name, contents in (("Caddyfile.base", base), ("Caddyfile", active)):
        descriptor = os.open(staging / name,
                             os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
    descriptor = os.open(staging / "manifest.json",
                         os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(receipt, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    directory_fd = os.open(staging, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    os.replace(staging, destination)
    parent_fd = os.open(config.backup_root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)
    return destination


def apply(*, config_file: Path, publication_file: Path) -> dict[str, object]:
    config = protected_cutover.load_config(config_file)
    with protected_cutover.host_lock():
        ip_origin_reconcile._no_interrupted_forward(config)
        api = protected_cutover._inspect(config.docker, "container", config.api)
        if api.get("Name") != "/" + config.api or api.get("State", {}).get("Running") is not True:
            raise ip_caddy_logging.IngressLogPolicyError("active_api_identity_unavailable")
        image = protected_cutover._inspect(config.docker, "image", api.get("Image", ""))
        revision = image.get("Config", {}).get("Labels", {}).get("atom.revision")
        if (protected_cutover.REVISION.fullmatch(revision or "") is None
                or image.get("Id") != api.get("Image")):
            raise ip_caddy_logging.IngressLogPolicyError("active_image_revision_unavailable")
        before = ip_forward_preflight._inspect_locked(
            config=config, publication_file=publication_file, revision=revision,
            allow_live_activity=True)
        publication = ip_forward_preflight._publication(
            publication_file, config, before["imageId"], require_template_image=False)
        source = Path(before["candidateDirectory"])
        controller = ip_forward_stage._controller(
            config=config, publication=publication, source=source)
        original = controller.base.read_bytes()
        secured = ip_caddy_logging.secure_base(original)
        if secured == original:
            return {"status": "ingress_log_policy_current", "revision": revision,
                    "originCount": before["activeOriginCount"]}
        backup = _backup_configuration(
            config, revision, original, controller.active.read_bytes())
        digest = controller.transition_base(secured, maintenance=False)
        try:
            after = ip_forward_preflight._inspect_locked(
                config=config, publication_file=publication_file, revision=revision,
                allow_live_activity=True)
            if (after["containerIds"] != before["containerIds"]
                    or after["activeOriginCount"] != before["activeOriginCount"]
                    or after["caddySha256"] != digest
                    or controller.base.read_bytes() != secured):
                raise ip_caddy_logging.IngressLogPolicyError(
                    "ingress_log_policy_verification_failed")
        except BaseException as error:
            try:
                controller.transition_base(original, maintenance=False)
            except BaseException:
                raise ip_caddy_logging.IngressLogPolicyError(
                    "ingress_log_policy_rollback_failed") from error
            raise
        return {"status": "ingress_log_policy_applied", "revision": revision,
                "originCount": after["activeOriginCount"],
                "backupDirectory": str(backup),
                "baseSha256": hashlib.sha256(secured).hexdigest(),
                "caddySha256": digest}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--publication-file", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        print(apply(config_file=args.config, publication_file=args.publication_file))
    except (protected_cutover.CutoverError,
            ip_origin_reconcile.OriginReconcileError,
            ip_forward_preflight.ForwardPreflightError,
            ip_forward_journal.JournalError,
            ip_forward_identity.IdentityError,
            ip_caddy_logging.IngressLogPolicyError, IngressError) as exc:
        parser.exit(2, str(exc) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
