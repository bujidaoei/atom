"""Read-only identity and data gate for a future schema-18 forward deployment.

This command never changes containers, databases, ingress or phase receipts. A
passing result is an observation, not a writer fence: the transaction must
repeat it under the deployment lock immediately before stopping writers.
"""

from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys

import ip_cutover_apply
import ip_cutover_rollback
import ip_forward_identity
import ip_forward_journal
import protected_cutover

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.ip_ingress import IngressError, IpIngressConfig, render_ip_routes  # noqa: E402
from app.project_origins import OriginRoute  # noqa: E402


class ForwardPreflightError(RuntimeError):
    """Stable, credential-free operational failure code."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ForwardPreflightError(code)


def _private_file(path: Path) -> bytes:
    try:
        protected_cutover._trusted_parents(path)
        info = path.lstat()
        _require(stat.S_ISREG(info.st_mode) and info.st_uid == 0
                 and stat.S_IMODE(info.st_mode) == 0o600, "insecure_forward_file")
        return path.read_bytes()
    except OSError as exc:
        raise ForwardPreflightError("forward_file_unavailable") from exc


def _candidate(config: protected_cutover.CutoverConfig,
               revision: str, record: dict[str, object]) -> Path:
    expected = config.backup_root / ("candidate-" + revision[:12])
    _require(record.get("candidateDirectory") == str(expected)
             and record.get("backupDirectory") == str(config.backup_root /
                                                        ("pre-" + revision[:12]))
             and expected != config.data and expected != config.broker_data,
             "active_generation_mismatch")
    return _private_candidate_path(config, expected)


def _private_candidate_path(config: protected_cutover.CutoverConfig,
                            expected: Path) -> Path:
    _require(expected.is_absolute() and expected != config.data
             and expected != config.broker_data,
             "active_generation_mismatch")
    try:
        protected_cutover._trusted_parents(expected)
        info = expected.lstat()
        _require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0
                 and stat.S_IMODE(info.st_mode) == 0o700,
                 "insecure_active_generation")
        for name in ("data", "broker", "caddy"):
            child = (expected / name).lstat()
            _require(stat.S_ISDIR(child.st_mode) and child.st_uid == 0,
                     "invalid_active_generation")
    except OSError as exc:
        raise ForwardPreflightError("active_generation_unavailable") from exc
    return expected


def _forward_candidate(config: protected_cutover.CutoverConfig,
                       revision: str, record: dict[str, object],
                       identity: dict[str, object]) -> Path:
    expected = config.backup_root / ("forward-candidate-" + revision[:12])
    _require(record["candidate"] is not None
             and record["candidate"]["directory"] == str(expected)
             and identity["candidateDirectory"] == str(expected)
             and record["capture"] is not None
             and record["capture"]["candidateDirectory"] == str(expected)
             and record["capture"]["backupDirectory"]
                 == identity["backupDirectory"],
             "active_generation_mismatch")
    return _private_candidate_path(config, expected)


def _publication(path: Path, config: protected_cutover.CutoverConfig,
                 image_id: str, *, require_template_image: bool = True) -> dict[str, str]:
    _private_file(path)
    try:
        values = ip_cutover_apply._private_env(path)
        required = ("ATOM_PUBLICATION_IMAGE", "ATOM_DATA_BIND", "ATOM_CADDY_CONFIG_DIR",
                    "ATOM_CADDY_IMAGE", "ATOM_PROXY_NETWORK", "ATOM_PUBLIC_IP",
                    "ATOM_FIRST_PORT", "ATOM_LAST_PORT", "ATOM_PREVIEW_UPSTREAM",
                    "ATOM_PUBLIC_UPSTREAM", "ATOM_ACME_DIRECTORY",
                    "ATOM_VERIFIER_NETWORK")
        _require(all(values.get(key) for key in required), "publication_config_incomplete")
        # This file is the first-cutover staging template. Its data/Caddy
        # bind values still refer to the preserved schema-10 generation; the
        # live mounts below, rather than these template fields, are trusted.
        _require(values["ATOM_PROXY_NETWORK"] == config.network,
                 "publication_config_mismatch")
        if require_template_image:
            actual_image = protected_cutover._inspect(
                config.docker, "image", values["ATOM_PUBLICATION_IMAGE"])
            _require(actual_image.get("Id") == image_id,
                     "publication_image_mismatch")
        first, last = int(values["ATOM_FIRST_PORT"]), int(values["ATOM_LAST_PORT"])
        _require(1024 <= first < last <= 65535 and last - first + 1 <= 512,
                 "invalid_origin_pool")
        return values
    except (KeyError, TypeError, ValueError, ip_cutover_apply.ApplyError) as exc:
        if isinstance(exc, ForwardPreflightError):
            raise
        raise ForwardPreflightError("publication_config_invalid") from exc


def _active_routes(database: Path, first: int, last: int) -> tuple[OriginRoute, ...]:
    protected_cutover._database(database, 18, broker=False)
    try:
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True,
                                     timeout=3)) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            rows = db.execute("SELECT o.project_id,o.purpose,o.port "
                              "FROM project_origin_ports o JOIN projects p "
                              "ON p.id=o.project_id ORDER BY o.port").fetchall()
            count = db.execute("SELECT count(*) FROM projects").fetchone()[0]
            outside = db.execute("SELECT count(*) FROM project_origin_ports "
                                 "WHERE port<? OR port>?", (first, last)).fetchone()[0]
            db.execute("ROLLBACK")
    except sqlite3.Error as exc:
        raise ForwardPreflightError("origin_ledger_unavailable") from exc
    _require(outside == 0 and len(rows) == count * 2 and len(rows) <= 512,
             "origin_ledger_incomplete")
    pairs: dict[str, set[str]] = {}
    ports = set()
    for project, purpose, port in rows:
        _require(type(project) is str and purpose in ("preview", "public")
                 and type(port) is int and first <= port <= last
                 and port not in ports, "origin_ledger_invalid")
        pairs.setdefault(project, set()).add(purpose)
        ports.add(port)
    _require(len(pairs) == count and all(roles == {"preview", "public"}
                                         for roles in pairs.values()),
             "origin_ledger_incomplete")
    return tuple(OriginRoute(*row) for row in rows)


def _bind(container: dict, source: Path, destination: str, *, writable: bool) -> None:
    matches = [mount for mount in container.get("Mounts") or ()
               if mount.get("Destination") == destination]
    _require(len(matches) == 1 and matches[0].get("Type") == "bind"
             and matches[0].get("Source") == str(source)
             and matches[0].get("RW") is writable,
             "active_service_bind_mismatch")


def _services(config: protected_cutover.CutoverConfig, candidate: Path,
              image_id: str, publication: dict[str, str]) -> dict[str, str]:
    names = {"api": config.api, "broker": config.broker,
             "preview": "atom-preview", "public": "atom-public",
             "verifier": "atom-verifier", "caddy": "atom-tls"}
    containers = {role: protected_cutover._inspect(config.docker, "container", name)
                  for role, name in names.items()}
    ids: dict[str, str] = {}
    for role, item in containers.items():
        _require(item.get("Name") == "/" + names[role]
                 and type(item.get("Id")) is str
                 and ip_cutover_rollback.IDENTITY.fullmatch(item["Id"]) is not None
                 and item.get("State", {}).get("Running") is True,
                 "active_service_identity_mismatch")
        if role != "caddy":
            _require(item.get("Image") == image_id
                     and item.get("State", {}).get("Health", {}).get("Status") == "healthy",
                     "active_service_image_or_health_mismatch")
        ids[role] = item["Id"]
    _require(len(set(ids.values())) == len(ids), "active_service_identity_mismatch")
    for role in ("api", "preview", "public", "verifier"):
        _bind(containers[role], candidate / "data", "/data", writable=True)
    _bind(containers["broker"], candidate / "broker", "/broker", writable=True)
    _bind(containers["caddy"], candidate / "caddy", "/etc/caddy", writable=False)
    _require(containers["api"].get("HostConfig", {}).get("NetworkMode") == config.network
             and containers["broker"].get("HostConfig", {}).get("NetworkMode")
                 == "container:" + ids["api"]
             and all(containers[role].get("HostConfig", {}).get("NetworkMode")
                     == config.network for role in ("preview", "public"))
             and containers["verifier"].get("HostConfig", {}).get("NetworkMode")
                 == publication["ATOM_VERIFIER_NETWORK"]
             and containers["caddy"].get("HostConfig", {}).get("NetworkMode")
                 == config.network, "active_service_network_mismatch")
    _require(containers["api"].get("HostConfig", {}).get("PortBindings") == {
                 "80/tcp": [{"HostIp": "127.0.0.1",
                             "HostPort": str(config.loopback_port)}]}
             and all(not containers[role].get("HostConfig", {}).get("PortBindings")
                     for role in ("broker", "preview", "public", "verifier"))
             and all(containers[role].get("HostConfig", {}).get("ReadonlyRootfs") is True
                     for role in ("broker", "preview", "public", "verifier")),
             "active_service_exposure_mismatch")
    caddy_image = protected_cutover._inspect(config.docker, "image",
                                              publication["ATOM_CADDY_IMAGE"])
    _require(containers["caddy"].get("Image") == caddy_image.get("Id")
             and containers["caddy"].get("HostConfig", {}).get("PortBindings", {})
                 .get("443/tcp") == [{"HostIp": "", "HostPort": "443"}],
             "active_ingress_profile_mismatch")
    for port in range(int(publication["ATOM_FIRST_PORT"]),
                      int(publication["ATOM_LAST_PORT"]) + 1):
        _require(containers["caddy"].get("HostConfig", {}).get("PortBindings", {})
                 .get(f"{port}/tcp") == [{"HostIp": "", "HostPort": str(port)}],
                 "active_ingress_profile_mismatch")
    return ids


def _target(config: protected_cutover.CutoverConfig, *, source: Path,
            revision: str, image_id: str, current_revision: str,
            current_image: str, candidate: Path) -> dict[str, str]:
    _require(protected_cutover.REVISION.fullmatch(revision) is not None
             and protected_cutover.IMAGE.fullmatch(image_id) is not None
             and revision != current_revision and image_id != current_image,
             "invalid_successor_identity")
    _require(source.is_absolute() and source.is_dir() and not source.is_symlink()
             and source != candidate and source not in candidate.parents
             and candidate not in source.parents
             and source != config.backup_root
             and source not in config.backup_root.parents
             and config.backup_root not in source.parents,
             "invalid_successor_checkout")
    _require(protected_cutover._command([
        "git", "-c", f"safe.directory={source}", "-C", str(source),
        "rev-parse", "HEAD"]) == revision, "successor_revision_mismatch")
    _require(protected_cutover._command([
        "git", "-c", f"safe.directory={source}", "-C", str(source),
        "status", "--porcelain"]) == "", "successor_checkout_dirty")
    image = protected_cutover._inspect(config.docker, "image", image_id)
    _require(image.get("Id") == image_id and image.get("Config", {})
             .get("Labels", {}).get("atom.revision") == revision,
             "successor_image_mismatch")
    return {"revision": revision, "imageId": image_id}


def _inspect_locked(*, config: protected_cutover.CutoverConfig,
                    publication_file: Path, revision: str,
                    successor_source: Path | None = None,
                    successor_revision: str | None = None,
                    successor_image: str | None = None) -> dict[str, object]:
    """Inspect under the caller's already-held host deployment lock."""
    _require(getattr(os, "geteuid", lambda: -1)() == 0, "root_required")
    _require(protected_cutover.REVISION.fullmatch(revision) is not None,
             "invalid_release_identity")
    _require((successor_source is None and successor_revision is None
              and successor_image is None)
             or (successor_source is not None and successor_revision is not None
                 and successor_image is not None), "incomplete_successor_identity")
    forward = ip_forward_journal.ForwardJournal(config, revision).read()
    if forward is None:
        record = protected_cutover.PhaseLedger(config.state_dir, revision).read()
        _require(record is not None and record.get("schemaVersion") == 1
                 and record.get("outcome") in {"awaiting_acceptance", "completed"}
                 and type(record.get("imageId")) is str
                 and protected_cutover.IMAGE.fullmatch(record["imageId"]) is not None,
                 "active_ledger_mismatch")
        image_id = record["imageId"]
        candidate = _candidate(config, revision, record)
        expected_ids = None
    else:
        _require(forward["phase"] in {"awaiting_acceptance",
                                      "successor_retained", "accepted"},
                 "active_forward_phase_mismatch")
        identity_forward = ip_forward_identity.read(
            config.state_dir / (revision + ".forward.json"),
            config=config, successor_revision=revision)
        _require(identity_forward["successorRevision"] == revision,
                 "active_forward_identity_mismatch")
        candidate = _forward_candidate(
            config, revision, forward, identity_forward)
        image_id = forward["candidate"]["imageId"]
        expected_ids = forward["candidate"]["containerIds"]
    publication = _publication(
        publication_file, config, image_id,
        require_template_image=forward is None)
    image = protected_cutover._inspect(config.docker, "image", image_id)
    _require(image.get("Id") == image_id and image.get("Config", {})
             .get("Labels", {}).get("atom.revision") == revision,
             "active_image_revision_mismatch")
    protected_cutover._database(candidate / "broker" / "registry.db", 3, broker=True)
    routes = _active_routes(candidate / "data" / "atom.db",
                            int(publication["ATOM_FIRST_PORT"]),
                            int(publication["ATOM_LAST_PORT"]))
    ids = _services(config, candidate, image_id, publication)
    if expected_ids is None:
        identity = ip_cutover_rollback._identity(config.state_dir /
                                                 (revision + ".identity.json"))
        _require(identity["revision"] == revision
                 and identity["candidateImageId"] == image_id
                 and ip_cutover_rollback._old_locations(identity) == {
                     role: name + "-rollback" for role, name in
                     ip_cutover_rollback.DEFAULT_CONTAINERS.items()},
                 "preserved_source_identity_mismatch")
    else:
        _require(ids == expected_ids,
                 "active_forward_container_identity_mismatch")
    directory = candidate / "caddy"
    try:
        base = (directory / "Caddyfile.base").read_bytes()
        active = (directory / "Caddyfile").read_bytes()
        _require(0 < len(base) <= 1024 * 1024
                 and 0 < len(active) <= 1024 * 1024
                 and not (directory / "Caddyfile.base").is_symlink()
                 and not (directory / "Caddyfile").is_symlink(),
                 "active_ingress_file_invalid")
        expected = render_ip_routes(base.decode("utf-8"), routes,
            IpIngressConfig(publication["ATOM_PUBLIC_IP"],
                            publication["ATOM_PREVIEW_UPSTREAM"],
                            publication["ATOM_PUBLIC_UPSTREAM"],
                            publication["ATOM_ACME_DIRECTORY"])).encode("utf-8")
    except (OSError, UnicodeError, IngressError) as exc:
        raise ForwardPreflightError("active_ingress_file_invalid") from exc
    # The cutover receipt records the *initial* Caddy digest. New projects
    # legitimately add origins later, so the current committed ledger is
    # the authority for the live config rather than that historical hash.
    _require(active == expected,
             "active_ingress_ledger_mismatch")
    result = {"status": "current_generation_verified", "revision": revision,
            "imageId": image_id, "candidateDirectory": str(candidate),
            "containerIds": ids, "activeOriginCount": len(routes),
            "caddySha256": hashlib.sha256(active).hexdigest()}
    if successor_source is not None:
        result["successor"] = _target(
            config, source=successor_source, revision=successor_revision,
            image_id=successor_image, current_revision=revision,
            current_image=image_id, candidate=candidate)
        result["status"] = "ready_for_forward_transaction"
    return result


def inspect_current(*, config_file: Path, publication_file: Path,
                    revision: str, successor_source: Path | None = None,
                    successor_revision: str | None = None,
                    successor_image: str | None = None) -> dict[str, object]:
    """Public read-only command: hold the host lock for the entire check."""
    config = protected_cutover.load_config(config_file)
    with protected_cutover.host_lock():
        return _inspect_locked(config=config, publication_file=publication_file,
                               revision=revision, successor_source=successor_source,
                               successor_revision=successor_revision,
                               successor_image=successor_image)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--publication-file", required=True, type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--successor-source", type=Path)
    parser.add_argument("--successor-revision")
    parser.add_argument("--successor-image")
    args = parser.parse_args(argv)
    try:
        result = inspect_current(config_file=args.config,
                                 publication_file=args.publication_file,
                                 revision=args.revision,
                                 successor_source=args.successor_source,
                                 successor_revision=args.successor_revision,
                                 successor_image=args.successor_image)
    except (ForwardPreflightError, protected_cutover.CutoverError,
            ip_cutover_rollback.RollbackError) as exc:
        parser.exit(2, str(exc) + "\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
