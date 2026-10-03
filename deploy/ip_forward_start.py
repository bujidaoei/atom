"""Start and seal a schema-18 successor behind strict-TLS maintenance.

Internal same-lock phase after source IDs have been held. Canonical names are
freed, but the old generation remains stopped and untouched. Ordinary startup
failures remove only verified successor containers, then restore the exact
source generation. A crash requires journal-guided reconciliation.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import sys
import time

import candidate_write_fence
import ip_cutover_apply
import ip_cutover_rollback
import ip_forward_candidate
import ip_forward_hold
import ip_forward_identity
import ip_forward_preflight
import ip_forward_stage
import protected_cutover

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.ip_ingress import probe_ip_maintenance_routes


class StartError(RuntimeError):
    """Stable, credential-free successor startup failure code."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise StartError(code)


@dataclass(frozen=True)
class StartedCandidate:
    ids: dict[str, str]
    baseline_path: Path
    baseline_sha256: str
    maintenance_sha256: str


def _project(revision: str) -> str:
    _require(protected_cutover.REVISION.fullmatch(revision) is not None,
             "invalid_forward_revision")
    return "atom-forward-" + revision[:12]


def _name(config: protected_cutover.CutoverConfig, role: str) -> str:
    return ip_forward_identity._name(config, role)


def _current(config: protected_cutover.CutoverConfig, role: str) -> dict | None:
    return ip_cutover_rollback._inspect(_name(config, role))


def _bind(item: dict, source: Path, destination: str, *, writable: bool) -> None:
    mounts = [mount for mount in item.get("Mounts") or ()
              if mount.get("Destination") == destination]
    _require(len(mounts) == 1 and mounts[0].get("Type") == "bind"
             and mounts[0].get("Source") == str(source)
             and mounts[0].get("RW") is writable,
             "forward_candidate_bind_mismatch")


def _profile(*, config: protected_cutover.CutoverConfig,
             role: str, item: dict, image: str,
             prepared: ip_forward_candidate.PreparedCandidate,
             project: str, publication: dict[str, str]) -> str:
    """Verify an owned canonical container before trusting or deleting it."""
    expected_name = _name(config, role)
    identifier = item.get("Id")
    _require(item.get("Name") == "/" + expected_name
             and type(identifier) is str
             and ip_forward_identity.HEX64.fullmatch(identifier) is not None,
             "forward_candidate_identity_changed")
    expected_image = (protected_cutover._inspect(
        config.docker, "image", publication["ATOM_CADDY_IMAGE"]).get("Id")
        if role == "caddy" else image)
    _require(item.get("Image") == expected_image,
             "forward_candidate_image_mismatch")
    if role in ("api", "preview", "public", "verifier"):
        _bind(item, prepared.directory / "data", "/data", writable=True)
    elif role == "broker":
        _bind(item, prepared.directory / "broker", "/broker", writable=True)
    else:
        _bind(item, prepared.directory / "caddy", "/etc/caddy", writable=False)
    if role in ("preview", "public", "verifier", "caddy"):
        _require(item.get("Config", {}).get("Labels", {}).get(
            "com.docker.compose.project") == project,
            "forward_candidate_project_mismatch")
    if role in prepared.service_ips:
        network = (item.get("NetworkSettings", {}).get("Networks", {})
                   .get(config.network, {}))
        address = network.get("IPAddress")
        pinned = (network.get("IPAMConfig") or {}).get("IPv4Address")
        # Stopped containers may release their active address; the pinned
        # assignment and exact source-free bridge are still the authority.
        _require(pinned == prepared.service_ips[role]
                 and (address in ("", pinned)),
                 "forward_candidate_ip_mismatch")
    if role == "api":
        _require(item.get("HostConfig", {}).get("NetworkMode") == config.network
                 and item.get("HostConfig", {}).get("PortBindings") == {
                    "80/tcp": [{"HostIp": "127.0.0.1",
                                "HostPort": str(config.loopback_port)}]},
                 "forward_candidate_api_profile_mismatch")
    elif role == "broker":
        api = _current(config, "api")
        _require(api is not None and item.get("HostConfig", {}).get("NetworkMode")
                 == "container:" + api["Id"]
                 and item.get("HostConfig", {}).get("ReadonlyRootfs") is True,
                 "forward_candidate_broker_profile_mismatch")
    elif role == "verifier":
        _require(item.get("HostConfig", {}).get("NetworkMode")
                 == publication["ATOM_VERIFIER_NETWORK"]
                 and not item.get("HostConfig", {}).get("PortBindings")
                 and item.get("HostConfig", {}).get("ReadonlyRootfs") is True,
                 "forward_candidate_verifier_profile_mismatch")
    else:
        _require(item.get("HostConfig", {}).get("NetworkMode") == config.network,
                 "forward_candidate_network_mismatch")
        if role in ("preview", "public"):
            _require(not item.get("HostConfig", {}).get("PortBindings")
                     and item.get("HostConfig", {}).get("ReadonlyRootfs") is True,
                     "forward_candidate_content_profile_mismatch")
    if role == "caddy":
        bindings = item.get("HostConfig", {}).get("PortBindings") or {}
        first, last = int(publication["ATOM_FIRST_PORT"]), int(
            publication["ATOM_LAST_PORT"])
        expected = {"443/tcp": [{"HostIp": "", "HostPort": "443"}]}
        expected.update({f"{port}/tcp": [{"HostIp": "", "HostPort": str(port)}]
                         for port in range(first, last + 1)})
        _require(bindings == expected,
                 "forward_candidate_caddy_ports_mismatch")
    return identifier


def _wait_healthy(config: protected_cutover.CutoverConfig, role: str,
                  expected_id: str, *, seconds: int = 300) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        item = _current(config, role)
        _require(item is not None and item.get("Id") == expected_id,
                 "forward_candidate_identity_changed")
        if (item.get("State", {}).get("Running") is True
                and item.get("State", {}).get("Health", {}).get("Status")
                == "healthy"):
            return
        time.sleep(2)
    raise StartError("forward_candidate_health_timeout")


def _compose(source: Path, prepared: ip_forward_candidate.PreparedCandidate,
             revision: str, filename: str, *services: str) -> None:
    ip_cutover_apply._compose(source, prepared.compose_env, filename,
                              "-p", _project(revision), "up", "-d", *services)


def _create_pair(config: protected_cutover.CutoverConfig,
                 prepared: ip_forward_candidate.PreparedCandidate,
                 image: str, publication: dict[str, str]) -> None:
    ip_cutover_apply._command([
        str(config.docker), "container", "create", "--name", config.api,
        "--network", config.network, "--ip", prepared.service_ips["api"],
        "--publish", f"127.0.0.1:{config.loopback_port}:80",
        "--volume", f"{prepared.directory / 'data'}:/data",
        "--env-file", str(prepared.api_env), "--restart", "unless-stopped",
        "--log-driver", "local", "--log-opt", "max-size=10m",
        "--log-opt", "max-file=3", "--workdir", "/app/backend", image],
        timeout=45)
    ip_cutover_apply._command([
        str(config.docker), "network", "connect",
        publication["ATOM_VERIFIER_NETWORK"], config.api], timeout=20)
    ip_cutover_apply._command([
        str(config.docker), "container", "start", config.api], timeout=45)
    ip_cutover_apply._command([
        str(config.docker), "container", "create", "--name", config.broker,
        "--network", "container:" + config.api, "--env-file",
        str(prepared.broker_env), "--volume",
        f"{config.docker}:{config.docker}:ro", "--volume",
        f"{prepared.directory / 'broker'}:/broker", "--volume",
        f"{config.docker_socket}:{config.docker_socket}",
        "--read-only", "--tmpfs", "/tmp:size=32m", "--security-opt",
        "no-new-privileges", "--restart", "unless-stopped",
        "--log-driver", "local", "--log-opt", "max-size=10m",
        "--log-opt", "max-file=3", "--workdir", "/app/backend", image,
        "/app/backend/.venv/bin/python", "-m", "app.sandbox"], timeout=45)
    ip_cutover_apply._command([
        str(config.docker), "container", "start", config.broker], timeout=45)


def _confirm_held(config: protected_cutover.CutoverConfig,
                  held: ip_forward_hold.HeldSource) -> None:
    _require(isinstance(held, ip_forward_hold.HeldSource)
             and set(held.ids) == set(ip_forward_identity.ROLES)
             and set(held.names) == set(ip_forward_identity.ROLES),
             "invalid_forward_held_source")
    for role in ip_forward_identity.ROLES:
        ip_forward_hold._inspect(config, held.ids[role], held.names[role],
                                 running=False)
        _require(_current(config, role) is None,
                 "forward_canonical_name_occupied")


def _cleanup_candidate(*, config: protected_cutover.CutoverConfig,
                       prepared: ip_forward_candidate.PreparedCandidate,
                       image: str, project: str,
                       publication: dict[str, str]) -> None:
    """Delete only canonical successor containers with proven exact profiles."""
    for role in ("caddy", "verifier", "preview", "public", "broker", "api"):
        item = _current(config, role)
        if item is None:
            continue
        identifier = _profile(config=config, role=role, item=item,
            image=image, prepared=prepared, project=project,
            publication=publication)
        ip_forward_hold._run(config, "container", "rm", "--force",
                             identifier, timeout=105)
        _require(_current(config, role) is None,
                 "forward_candidate_cleanup_failed")


def start(*, config: protected_cutover.CutoverConfig,
          stage: ip_forward_stage.ForwardStage,
          prepared: ip_forward_candidate.PreparedCandidate,
          held: ip_forward_hold.HeldSource,
          successor_source: Path, successor_revision: str,
          successor_image: str, publication_file: Path) -> StartedCandidate:
    """Boot six candidate services under maintenance, seal state and journal."""
    _require(isinstance(config, protected_cutover.CutoverConfig)
             and isinstance(stage, ip_forward_stage.ForwardStage)
             and isinstance(prepared, ip_forward_candidate.PreparedCandidate)
             and successor_source.is_absolute()
             and publication_file.is_absolute()
             and protected_cutover.REVISION.fullmatch(successor_revision) is not None
             and protected_cutover.IMAGE.fullmatch(successor_image) is not None
             and stage.journal.read()["phase"] == "candidate_intent",
             "invalid_forward_start")
    identity = ip_forward_identity.read(
        stage.journal.identity_path, config=config,
        successor_revision=successor_revision)
    _require(held.ids == identity["containerIds"]
             and held.names == identity["heldNames"]
             and prepared.service_ips == identity["serviceIps"]
             and prepared.directory == Path(identity["candidateDirectory"])
             and successor_image == identity["successorImageId"],
             "forward_start_identity_mismatch")
    publication = stage.publication
    project = _project(successor_revision)
    _confirm_held(config, held)
    try:
        _compose(successor_source, prepared, successor_revision,
                 "compose.ip-verifier.yml", "atom-verifier")
        _compose(successor_source, prepared, successor_revision,
                 "compose.ip-publication.yml", "atom-preview", "atom-public")
        _create_pair(config, prepared, successor_image, publication)
        _compose(successor_source, prepared, successor_revision,
                 "compose.ip-ingress.yml", "atom-tls")
        ids: dict[str, str] = {}
        for role in ip_forward_identity.ROLES:
            item = _current(config, role)
            _require(item is not None, "forward_candidate_missing")
            ids[role] = _profile(config=config, role=role, item=item,
                image=successor_image, prepared=prepared, project=project,
                publication=publication)
        _require(len(set(ids.values())) == len(ids)
                 and not set(ids.values()) & set(held.ids.values()),
                 "forward_candidate_id_collision")
        for role in ("api", "broker", "preview", "public", "verifier"):
            _wait_healthy(config, role, ids[role])
        _require(_current(config, "caddy").get("State", {}).get("Running") is True,
                 "forward_candidate_caddy_unavailable")
        active = prepared.directory / "caddy" / "Caddyfile"
        _require(hashlib.sha256(active.read_bytes()).hexdigest()
                 == prepared.maintenance_sha256,
                 "forward_candidate_caddy_changed")
        ip_cutover_apply._maintenance_probe(publication["ATOM_PUBLIC_IP"])
        probe_ip_maintenance_routes(stage.routes, publication["ATOM_PUBLIC_IP"])
        _require(ip_forward_preflight._active_routes(
            prepared.directory / "data" / "atom.db",
            int(publication["ATOM_FIRST_PORT"]),
            int(publication["ATOM_LAST_PORT"])) == stage.routes,
            "forward_candidate_origins_changed")
        baseline_path = config.state_dir / (
            successor_revision + ".forward-baseline.json")
        baseline = candidate_write_fence.capture_baseline(
            baseline_path, candidate_directory=prepared.directory,
            revision=successor_revision, candidate_image=successor_image)
        candidate_receipt = {"directory": str(prepared.directory),
            "imageId": successor_image, "containerIds": ids,
            "baselineSha256": baseline,
            "caddySha256": prepared.maintenance_sha256}
        stage.journal.advance("candidate_ready", candidate=candidate_receipt)
        return StartedCandidate(ids, baseline_path, baseline,
                                prepared.maintenance_sha256)
    except BaseException as failure:
        try:
            _cleanup_candidate(config=config, prepared=prepared,
                image=successor_image, project=project,
                publication=publication)
            ip_forward_hold.restore(config=config, stage=stage,
                identity=identity, publication_file=publication_file)
        except BaseException as recovery_failure:
            raise StartError("forward_candidate_recovery_failed") from recovery_failure
        raise StartError("forward_candidate_start_failed") from failure
