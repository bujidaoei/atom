"""Read-only, bounded certificate health check for every committed IP origin.

Run from the root-owned operator archive. A failed check exits nonzero so the
independent systemd unit exposes an actionable renewal/ingress alarm. It never
modifies publication state, TLS material or ingress configuration.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
from pathlib import Path
import socket
import ssl
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import ip_forward_identity
import ip_forward_journal
import ip_forward_preflight
import ip_origin_reconcile
import protected_cutover
from app.ip_ingress import IngressError


WARN_BEFORE = timedelta(hours=36)
CONNECT_TIMEOUT = 3.0
MAX_WORKERS = 16


class CertificateWatchError(RuntimeError):
    """Stable operator failure code; never includes certificate or credentials."""


def _targets(config_file: Path, publication_file: Path) -> tuple[str, tuple[int, ...]]:
    config = protected_cutover.load_config(config_file)
    with protected_cutover.host_lock():
        ip_origin_reconcile._no_interrupted_forward(config)
        api = protected_cutover._inspect(config.docker, "container", config.api)
        if (api.get("Name") != "/" + config.api
                or api.get("State", {}).get("Running") is not True):
            raise CertificateWatchError("active_api_identity_unavailable")
        image = protected_cutover._inspect(config.docker, "image", api.get("Image", ""))
        revision = image.get("Config", {}).get("Labels", {}).get("atom.revision")
        if (protected_cutover.REVISION.fullmatch(revision or "") is None
                or image.get("Id") != api.get("Image")):
            raise CertificateWatchError("active_image_revision_unavailable")
        active = ip_forward_preflight._inspect_locked(
            config=config, publication_file=publication_file, revision=revision,
            allow_live_activity=True)
        publication = ip_forward_preflight._publication(
            publication_file, config, active["imageId"],
            require_template_image=False)
        routes = ip_forward_preflight._active_routes(
            Path(active["candidateDirectory"]) / "data" / "atom.db",
            int(publication["ATOM_FIRST_PORT"]),
            int(publication["ATOM_LAST_PORT"]), require_idle=False)
        if len(routes) != active["activeOriginCount"]:
            raise CertificateWatchError("origin_ledger_changed")
        try:
            public_ip = str(ipaddress.IPv4Address(publication["ATOM_PUBLIC_IP"]))
        except ipaddress.AddressValueError as exc:
            raise CertificateWatchError("invalid_public_ip") from exc
        return public_ip, (443, *(route.port for route in routes))


def _probe(ip: str, port: int, context: ssl.SSLContext) -> tuple[str, datetime]:
    try:
        with socket.create_connection((ip, port), timeout=CONNECT_TIMEOUT) as peer:
            with context.wrap_socket(peer, server_hostname=ip) as secured:
                certificate = secured.getpeercert()
                der = secured.getpeercert(binary_form=True)
        if not der or not certificate or not certificate.get("notAfter"):
            raise CertificateWatchError("certificate_missing")
        expiry = datetime.fromtimestamp(
            ssl.cert_time_to_seconds(certificate["notAfter"]), timezone.utc)
        return hashlib.sha256(der).hexdigest(), expiry
    except (OSError, ssl.SSLError, ValueError, OverflowError,
            CertificateWatchError) as exc:
        raise CertificateWatchError(f"certificate_probe_failed:{port}") from exc


def _summarize(results: tuple[tuple[str, datetime], ...], *,
               now: datetime) -> dict[str, object]:
    if not results or now.tzinfo is None:
        raise CertificateWatchError("certificate_result_invalid")
    fingerprints = {fingerprint for fingerprint, _ in results}
    if len(fingerprints) != 1:
        raise CertificateWatchError("certificate_inconsistent")
    earliest = min(expiry for _, expiry in results)
    if earliest <= now + WARN_BEFORE:
        raise CertificateWatchError("certificate_renewal_due")
    return {"status": "certificate_healthy", "originCount": len(results) - 1,
            "fingerprintSha256": next(iter(fingerprints)),
            "expiresAt": earliest.isoformat().replace("+00:00", "Z")}


def check(*, config_file: Path, publication_file: Path) -> dict[str, object]:
    ip, ports = _targets(config_file, publication_file)
    # The serving ledger bounds this to at most 512 project routes plus 443.
    try:
        context = ssl.create_default_context()
    except (OSError, ssl.SSLError) as exc:
        raise CertificateWatchError("trust_store_unavailable") from exc
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as workers:
        results = tuple(workers.map(
            lambda port: _probe(ip, port, context), ports))
    return _summarize(results, now=datetime.now(timezone.utc))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--publication-file", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(check(config_file=args.config,
                               publication_file=args.publication_file),
                         sort_keys=True))
    except (CertificateWatchError, protected_cutover.CutoverError,
            ip_origin_reconcile.OriginReconcileError,
            ip_forward_preflight.ForwardPreflightError,
            ip_forward_journal.JournalError,
            ip_forward_identity.IdentityError,
            IngressError, ValueError) as exc:
        parser.exit(2, str(exc) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
