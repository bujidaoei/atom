"""Protected schema-changing IP publication cutover for the existing Atom pair.

The old schema-10 data and containers are preserved. Every candidate database
is restored from a fresh paired backup and migrated only in its own directory.
On any failed phase, the exact old container IDs are restored through the
identity-fenced rollback path; the candidate and backup remain for inspection.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import stat
import subprocess
import sys
import time

import ip_cutover_env
import ip_cutover_rollback
import paired_backup
import protected_cutover


class ApplyError(RuntimeError):
    """Stable failure code; no command output, credential or page data."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ApplyError(code)


def _record(ledger: protected_cutover.PhaseLedger, *, outcome: str,
            image_id: str, details: dict[str, object]) -> None:
    previous = ledger.read()
    history = [] if previous is None else previous.get("phaseHistory", [])
    _require(type(history) is list and len(history) < 32,
             "invalid_phase_history")
    event = {"phase": outcome, "at": datetime.now(timezone.utc).isoformat(),
             "details": details}
    ledger.write(outcome=outcome, image_id=image_id,
                 details={**details, "phaseHistory": [*history, event]})


def _command(args: list[str], *, timeout: int = 120,
             environment: dict[str, str] | None = None) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                                check=False, env=environment)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ApplyError("cutover_command_unavailable") from exc
    if result.returncode:
        raise ApplyError("cutover_command_failed")
    return result.stdout.strip()


def _private_env(path: Path) -> dict[str, str]:
    info = path.lstat()
    _require(stat.S_ISREG(info.st_mode) and info.st_uid == 0
             and stat.S_IMODE(info.st_mode) == 0o600, "insecure_compose_environment")
    return ip_cutover_env._read_pairs(path.read_text(encoding="utf-8").splitlines())


def _json_command(args: list[str], *, timeout: int = 120,
                  environment: dict[str, str] | None = None) -> dict:
    try:
        value = json.loads(_command(args, timeout=timeout, environment=environment))
    except ValueError as exc:
        raise ApplyError("invalid_phase_receipt") from exc
    _require(type(value) is dict, "invalid_phase_receipt")
    return value


def _health(name: str, *, budget: int = 180) -> None:
    deadline = time.monotonic() + budget
    while time.monotonic() < deadline:
        item = ip_cutover_rollback._inspect(name)
        if (item is not None and item.get("State", {}).get("Running") is True
                and item.get("State", {}).get("Health", {}).get("Status") == "healthy"):
            return
        time.sleep(2)
    raise ApplyError("candidate_health_timeout")


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _private_directory(path: Path) -> None:
    if not path.exists():
        path.mkdir(mode=0o700)
    info = path.lstat()
    _require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0
             and stat.S_IMODE(info.st_mode) == 0o700,
             "insecure_candidate_directory")


@dataclass(frozen=True)
class Inputs:
    protected_file: Path
    publication_file: Path
    source: Path
    revision: str
    image_id: str
    candidate_caddy_ip: str

    def validate(self) -> None:
        _require(protected_cutover.REVISION.fullmatch(self.revision) is not None
                 and protected_cutover.IMAGE.fullmatch(self.image_id) is not None,
                 "invalid_release_identity")
        _require(self.source.is_absolute() and self.publication_file.is_absolute()
                 and self.protected_file.is_absolute(), "absolute_paths_required")
        try:
            parsed = ipaddress.ip_address(self.candidate_caddy_ip)
        except ValueError as exc:
            raise ApplyError("invalid_candidate_caddy_ip") from exc
        _require(parsed.version == 4 and parsed.compressed == self.candidate_caddy_ip
                 and not parsed.is_loopback and not parsed.is_unspecified,
                 "invalid_candidate_caddy_ip")


def _caddy_source(name: str, network: str, expected_image: str) -> Path:
    caddy = ip_cutover_rollback._inspect(name)
    _require(caddy is not None and caddy.get("State", {}).get("Running") is True,
             "old_caddy_unavailable")
    image = _command(["docker", "image", "inspect", "--format", "{{.Id}}",
                      expected_image], timeout=15)
    _require(caddy.get("Image") == image
             and caddy.get("HostConfig", {}).get("NetworkMode") == network
             and caddy.get("HostConfig", {}).get("PortBindings") == {
                 "443/tcp": [{"HostIp": "", "HostPort": "443"}]},
             "old_caddy_profile_mismatch")
    mounts = caddy.get("Mounts") or []
    sources = [Path(mount["Source"]) for mount in mounts
               if mount.get("Type") == "bind"
               and mount.get("Destination") == "/etc/caddy/Caddyfile"
               and mount.get("RW") is False]
    _require(len(sources) == 1 and sources[0].is_absolute()
             and sources[0].is_file() and not sources[0].is_symlink(),
             "old_caddy_file_mismatch")
    return sources[0]


def _candidate_address_free(network: str, address: str) -> None:
    raw = _command(["docker", "network", "inspect", network], timeout=15)
    try:
        rows = json.loads(raw)
        occupied = {item.get("IPv4Address", "").split("/", 1)[0]
                    for item in rows[0]["Containers"].values()}
        ranges = [ipaddress.ip_network(entry["Subnet"], strict=False)
                  for entry in rows[0]["IPAM"]["Config"]]
    except (ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
        raise ApplyError("invalid_ingress_network") from exc
    _require(address not in occupied and any(ipaddress.ip_address(address) in subnet
             for subnet in ranges), "candidate_caddy_ip_occupied")


def _origin_ports_free(first: int, last: int) -> None:
    for port in range(first, last + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            try:
                listener.bind(("0.0.0.0", port))
            except OSError as exc:
                raise ApplyError("origin_port_occupied") from exc


def _compose_environment(original: dict[str, str], candidate: Path,
                         image: str, candidate_ip: str) -> Path:
    values = dict(original)
    values.update({"ATOM_PUBLICATION_IMAGE": image,
                   "ATOM_DATA_BIND": str(candidate / "data"),
                   "ATOM_CADDY_CONFIG_DIR": str(candidate / "caddy"),
                   "ATOM_CADDY_PROXY_IP": candidate_ip})
    required = {"ATOM_CADDY_IMAGE", "ATOM_STORAGE_ENV_FILE", "ATOM_PROXY_NETWORK",
                "ATOM_CADDY_DATA_VOLUME", "ATOM_CADDY_CONFIG_VOLUME", "ATOM_PUBLIC_IP",
                "ATOM_FIRST_PORT", "ATOM_LAST_PORT", "ATOM_VERIFIER_NETWORK",
                "ATOM_VERIFIER_WORKER_IMAGE", "ATOM_VERIFIER_ID",
                "ATOM_VERIFIER_POLICY_PATH", "ATOM_DOCKER_CLI_PATH",
                "ATOM_VERIFIER_ENV_FILE", "ATOM_PREVIEW_UPSTREAM",
                "ATOM_PUBLIC_UPSTREAM", "ATOM_ACME_DIRECTORY"}
    _require(all(values.get(key) for key in required), "incomplete_compose_environment")
    path = candidate / "compose.env"
    ip_cutover_env._write_private(path, values)
    return path


def _compose(source: Path, environment: Path, filename: str, *args: str) -> None:
    _command(["docker", "compose", "--env-file", str(environment), "-f",
              str(source / "deploy" / filename), *args], timeout=240)


def _image_python(image: str, data: Path, module: str, args: list[str], *,
                  storage_env: Path | None = None, timeout: int = 600) -> dict:
    network = "bridge" if storage_env is not None else "none"
    command = ["docker", "run", "--rm", "--network", network, "--read-only",
               "--tmpfs", "/tmp:size=64m", "--volume", f"{data}:/data",
               "--workdir", "/app/backend"]
    if storage_env is not None:
        command += ["--env-file", str(storage_env)]
    command += ["--entrypoint", "/app/backend/.venv/bin/python", image,
                "-m", module, *args]
    return _json_command(command, timeout=timeout)


def _write_caddy_inputs(candidate: Path) -> tuple[Path, Path]:
    directory = candidate / "caddy"
    _private_directory(directory)
    base = directory / "Caddyfile.base"
    active = directory / "Caddyfile"
    contents = (candidate / "Caddyfile").read_bytes()
    _require(0 < len(contents) <= 1024 * 1024, "invalid_old_caddyfile")
    for path in (base, active):
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
    return base, active


def _legacy_rows(database: Path) -> list[tuple[str, str]]:
    try:
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=3) as connection:
            connection.execute("PRAGMA query_only=ON")
            rows = connection.execute("SELECT project_id,slug FROM publications "
                                      "WHERE live=1 ORDER BY project_id").fetchall()
    except sqlite3.Error as exc:
        raise ApplyError("legacy_inventory_unavailable") from exc
    _require(len(rows) <= 10000 and all(isinstance(project, str)
             and isinstance(slug, str) for project, slug in rows),
             "invalid_legacy_inventory")
    return rows


def _legacy_candidates(image: str, data: Path,
                       storage_env: Path) -> list[dict[str, str]]:
    candidates = []
    for project, slug in _legacy_rows(data / "atom.db"):
        result = _image_python(image, data, "app.legacy_publications", [
            "--database", "/data/atom.db", "--published-root", "/data/published",
            "--project-id", project, "--slug", slug],
            storage_env=storage_env, timeout=180)
        _require(result.get("project_id") == project and result.get("slug") == slug
                 and isinstance(result.get("revision_id"), str)
                 and isinstance(result.get("artifact_key"), str),
                 "legacy_inspection_mismatch")
        candidates.append({"projectId": project, "slug": slug,
                           "revisionId": result["revision_id"],
                           "artifactKey": result["artifact_key"]})
    return candidates


def _start_candidate_pair(config: protected_cutover.CutoverConfig,
                          candidate: Path, image: str, verifier_network: str) -> None:
    api_env = candidate / "private-env" / "api.env"
    broker_env = candidate / "private-env" / "broker.env"
    _command(["docker", "container", "rename", config.api,
              ip_cutover_rollback._rollback_name(config.api)], timeout=20)
    _command(["docker", "container", "rename", config.broker,
              ip_cutover_rollback._rollback_name(config.broker)], timeout=20)
    _command(["docker", "container", "create", "--name", config.api,
              "--network", config.network, "--publish",
              f"127.0.0.1:{config.loopback_port}:80", "--volume",
              f"{candidate / 'data'}:/data", "--env-file", str(api_env),
              "--restart", "unless-stopped", "--log-driver", "local",
              "--log-opt", "max-size=10m", "--log-opt", "max-file=3",
              "--workdir", "/app/backend", image], timeout=45)
    _command(["docker", "network", "connect", verifier_network, config.api], timeout=20)
    _command(["docker", "container", "start", config.api], timeout=45)
    # The console may briefly retry while its broker starts; the old pair is
    # already stopped, so the copied broker identity can take the daemon lease.
    _command(["docker", "container", "create", "--name", config.broker,
              "--network", f"container:{config.api}", "--env-file", str(broker_env),
              "--volume", f"{config.docker}:{config.docker}:ro", "--volume",
              f"{candidate / 'broker'}:/broker", "--volume",
              f"{config.docker_socket}:{config.docker_socket}",
              "--read-only", "--tmpfs", "/tmp:size=32m", "--security-opt",
              "no-new-privileges", "--restart", "unless-stopped", "--log-driver",
              "local", "--log-opt", "max-size=10m", "--log-opt", "max-file=3",
              "--workdir", "/app/backend", image,
              "/app/backend/.venv/bin/python", "-m", "app.sandbox"], timeout=45)
    _command(["docker", "container", "start", config.broker], timeout=45)
    _health(config.broker, budget=300)
    _health(config.api, budget=300)


def _ingress(source: Path, compose_env: Path, candidate: Path,
             publication: dict[str, str], config: protected_cutover.CutoverConfig) -> str:
    _command(["docker", "container", "stop", "--time", "15", "atom-tls"], timeout=30)
    _command(["docker", "container", "rename", "atom-tls", "atom-tls-rollback"],
             timeout=20)
    _compose(source, compose_env, "compose.ip-ingress.yml", "up", "-d", "atom-tls")
    item = ip_cutover_rollback._inspect("atom-tls")
    _require(item is not None and item.get("State", {}).get("Running") is True,
             "candidate_caddy_unavailable")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(source / "backend")
    return _command([sys.executable, "-m", "app.ip_ingress_controller",
        "--db", str(candidate / "data" / "atom.db"),
        "--base", str(candidate / "caddy" / "Caddyfile.base"),
        "--active", str(candidate / "caddy" / "Caddyfile"),
        "--address", publication["ATOM_PUBLIC_IP"],
        "--preview-upstream", publication["ATOM_PREVIEW_UPSTREAM"],
        "--public-upstream", publication["ATOM_PUBLIC_UPSTREAM"],
        "--acme-directory", publication["ATOM_ACME_DIRECTORY"],
        "--container", "atom-tls",
        "--first-port", publication["ATOM_FIRST_PORT"],
        "--last-port", publication["ATOM_LAST_PORT"]],
        timeout=360, environment=environment)


def _import_legacy(candidates: list[dict[str, str]], *, image: str, data: Path,
                   storage_env: Path, publication: dict[str, str]) -> list[dict]:
    receipts = []
    for candidate in candidates:
        result = _image_python(image, data, "app.legacy_publications", [
            "--database", "/data/atom.db", "--published-root", "/data/published",
            "--project-id", candidate["projectId"], "--slug", candidate["slug"],
            "--apply", "--expect-revision", candidate["revisionId"],
            "--expect-artifact", candidate["artifactKey"],
            "--address", publication["ATOM_PUBLIC_IP"],
            "--first-port", publication["ATOM_FIRST_PORT"],
            "--last-port", publication["ATOM_LAST_PORT"]],
            storage_env=storage_env, timeout=180)
        receipts.append(result)
    return receipts


def _publication_inputs(inputs: Inputs,
                        config: protected_cutover.CutoverConfig) -> dict[str, str]:
    values = _private_env(inputs.publication_file)
    required = {"ATOM_PUBLICATION_IMAGE", "ATOM_CADDY_IMAGE",
                "ATOM_STORAGE_ENV_FILE", "ATOM_DATA_BIND", "ATOM_PROXY_NETWORK",
                "ATOM_CADDY_PROXY_IP", "ATOM_PUBLIC_IP", "ATOM_FIRST_PORT",
                "ATOM_LAST_PORT", "ATOM_VERIFIER_NETWORK",
                "ATOM_VERIFIER_WORKER_IMAGE", "ATOM_VERIFIER_POLICY_PATH",
                "ATOM_VERIFIER_ENV_FILE", "ATOM_PREVIEW_UPSTREAM",
                "ATOM_PUBLIC_UPSTREAM", "ATOM_ACME_DIRECTORY"}
    _require(all(values.get(key) for key in required)
             and values["ATOM_DATA_BIND"] == str(config.data)
             and values["ATOM_PROXY_NETWORK"] == config.network
             and values["ATOM_CADDY_PROXY_IP"] != inputs.candidate_caddy_ip
             and values["ATOM_VERIFIER_NETWORK"] != config.network,
             "publication_config_mismatch")
    candidate_image = _command(["docker", "image", "inspect", "--format", "{{.Id}}",
                                values["ATOM_PUBLICATION_IMAGE"]], timeout=15)
    _require(candidate_image == inputs.image_id, "candidate_image_mismatch")
    first, last = int(values["ATOM_FIRST_PORT"]), int(values["ATOM_LAST_PORT"])
    _require(1024 <= first < last <= 65535 and last - first + 1 <= 512,
             "invalid_origin_pool")
    address = ipaddress.ip_address(values["ATOM_PUBLIC_IP"])
    _require(address.version == 4 and address.compressed == values["ATOM_PUBLIC_IP"],
             "invalid_public_address")
    _require(Path(values["ATOM_VERIFIER_POLICY_PATH"]).is_file(),
             "verifier_policy_missing")
    _command(["docker", "network", "inspect", values["ATOM_VERIFIER_NETWORK"]],
             timeout=15)
    _candidate_address_free(config.network, inputs.candidate_caddy_ip)
    _origin_ports_free(first, last)
    for name in ("atom-preview", "atom-public", "atom-verifier",
                 "atom-tls-rollback", config.api + "-rollback",
                 config.broker + "-rollback"):
        _require(ip_cutover_rollback._inspect(name) is None,
                 "candidate_name_occupied")
    return values


def _receipt_reason(error: BaseException) -> str:
    if isinstance(error, (ApplyError, protected_cutover.CutoverError,
                          paired_backup.BackupError,
                          ip_cutover_env.EnvironmentError,
                          ip_cutover_rollback.RollbackError)):
        return str(error)
    return "cutover_unavailable"


def apply(inputs: Inputs, *, rehearsal: bool = False) -> dict[str, object]:
    inputs.validate()
    _require(getattr(os, "geteuid", lambda: -1)() == 0, "root_required")
    config = protected_cutover.load_config(inputs.protected_file)
    ledger = protected_cutover.PhaseLedger(config.state_dir, inputs.revision)
    backup = config.backup_root / ("pre-" + inputs.revision[:12])
    candidate = config.backup_root / ("candidate-" + inputs.revision[:12])
    identity_path = config.state_dir / (inputs.revision + ".identity.json")
    with protected_cutover.host_lock():
        _require(not candidate.exists() and not identity_path.exists(),
                 "candidate_already_exists")
        old = protected_cutover.preflight(config, source=inputs.source,
                                          revision=inputs.revision,
                                          image_id=inputs.image_id)
        publication = _publication_inputs(inputs, config)
        caddy_source = _caddy_source("atom-tls", config.network,
                                     publication["ATOM_CADDY_IMAGE"])
        _record(ledger, outcome="preflight_passed", image_id=inputs.image_id,
                     details={"oldImageId": old["oldImageId"],
                              "backupDirectory": str(backup)})
        identity = ip_cutover_rollback.capture_identity(
            identity_path, revision=inputs.revision, candidate_image=inputs.image_id)
        _record(ledger, outcome="old_identified", image_id=inputs.image_id,
                     details={"identitySha256": _hash(identity_path)})
        console_url = "https://" + publication["ATOM_PUBLIC_IP"] + "/atom/"
        try:
            _command(["docker", "container", "stop", "--time", "90", config.broker],
                     timeout=110)
            _command(["docker", "container", "stop", "--time", "30", config.api],
                     timeout=50)
            _record(ledger, outcome="writers_stopped", image_id=inputs.image_id,
                         details={"oldImageId": old["oldImageId"]})

            tool = Path(__file__).with_name("paired_backup.py")
            captured = _json_command([sys.executable, str(tool), "capture",
                "--data", str(config.data), "--broker", str(config.broker_data),
                "--caddy", str(caddy_source), "--destination", str(backup),
                "--image-id", old["oldImageId"], "--app-schema", str(config.app_schema),
                "--broker-schema", str(config.broker_schema)], timeout=900)
            checked = _json_command([sys.executable, str(tool), "verify", str(backup)],
                                    timeout=300)
            _require(captured == checked and checked.get("status") == "verified",
                     "paired_backup_mismatch")
            _record(ledger, outcome="backup_verified", image_id=inputs.image_id,
                         details={"manifestSha256": checked["manifestSha256"]})

            restored = _json_command([sys.executable, str(tool), "restore", str(backup),
                                      str(candidate)], timeout=900)
            _require(restored == checked, "candidate_restore_mismatch")
            manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
            source_digest = manifest["entries"]["data"]["atom.db"]["sha256"]
            counts = manifest["counts"]["data"]
            prepared = _image_python(inputs.image_id, candidate / "data",
                "app.publication_prepare", ["--database", "/data/atom.db",
                "--backup-dir", "/data/migration-predecessors",
                "--source-sha256", source_digest,
                "--expect-projects", str(counts["projects"]),
                "--expect-revisions", str(counts["revision_records"]),
                "--expect-artifacts", str(counts["revision_artifacts"]),
                "--first-port", publication["ATOM_FIRST_PORT"],
                "--last-port", publication["ATOM_LAST_PORT"]], timeout=600)
            _require(prepared.get("schema") == 18
                     and prepared.get("originPairs") == counts["projects"],
                     "candidate_preparation_mismatch")
            _record(ledger, outcome="candidate_prepared", image_id=inputs.image_id,
                         details={"databaseSha256": prepared["databaseSha256"],
                                  "originPairs": prepared["originPairs"]})

            storage_file = Path(publication["ATOM_STORAGE_ENV_FILE"])
            transferred = _image_python(inputs.image_id, candidate / "data",
                "app.artifact_transfer", ["--database", "/data/atom.db",
                "--local-artifacts", "/data/artifacts"],
                storage_env=storage_file, timeout=1200)
            _require(transferred.get("artifact_count") == counts["revision_artifacts"],
                     "cos_inventory_mismatch")
            legacy = _legacy_candidates(inputs.image_id, candidate / "data", storage_file)
            _record(ledger, outcome="cos_verified", image_id=inputs.image_id,
                         details={"artifactCount": transferred["artifact_count"],
                                  "inventorySha256": transferred["inventory_sha256"],
                                  "legacyCount": len(legacy)})

            if rehearsal:
                ip_cutover_rollback.rollback(identity, console_url=console_url)
                _record(ledger, outcome="rolled_back", image_id=inputs.image_id,
                             details={"reason": "preparation_rehearsal_complete",
                                      "backupDirectory": str(backup),
                                      "candidateDirectory": str(candidate)})
                return ledger.read()

            _write_caddy_inputs(candidate)
            compose_env = _compose_environment(publication, candidate,
                                               inputs.image_id,
                                               inputs.candidate_caddy_ip)
            private_env = candidate / "private-env"
            _private_directory(private_env)
            ip_cutover_env.build(
                old_api=config.api, old_broker=config.broker,
                storage_file=storage_file,
                verifier_file=Path(publication["ATOM_VERIFIER_ENV_FILE"]),
                output_dir=private_env, candidate_image=inputs.image_id,
                worker_image=publication["ATOM_VERIFIER_WORKER_IMAGE"],
                seccomp_file=Path(publication["ATOM_VERIFIER_POLICY_PATH"]),
                public_ip=publication["ATOM_PUBLIC_IP"],
                first_port=int(publication["ATOM_FIRST_PORT"]),
                last_port=int(publication["ATOM_LAST_PORT"]))
            _compose(inputs.source, compose_env, "compose.ip-verifier.yml",
                     "up", "-d", "atom-verifier")
            _health("atom-verifier", budget=180)
            _compose(inputs.source, compose_env, "compose.ip-publication.yml",
                     "up", "-d", "atom-preview", "atom-public")
            _health("atom-preview", budget=180)
            _health("atom-public", budget=180)
            _record(ledger, outcome="private_services_ready", image_id=inputs.image_id,
                         details={"candidateDirectory": str(candidate)})

            _start_candidate_pair(config, candidate, inputs.image_id,
                                  publication["ATOM_VERIFIER_NETWORK"])
            _record(ledger, outcome="candidate_pair_ready", image_id=inputs.image_id,
                         details={"candidateDirectory": str(candidate)})

            ingress_digest = _ingress(inputs.source, compose_env, candidate,
                                      publication, config)
            _require(re.fullmatch(r"[0-9a-f]{64}", ingress_digest) is not None,
                     "invalid_ingress_receipt")
            _record(ledger, outcome="ingress_ready", image_id=inputs.image_id,
                         details={"caddySha256": ingress_digest})

            imported = _import_legacy(legacy, image=inputs.image_id,
                                      data=candidate / "data", storage_env=storage_file,
                                      publication=publication)
            _require(len(imported) == len(legacy), "legacy_import_count_mismatch")
            _record(ledger, outcome="awaiting_acceptance", image_id=inputs.image_id,
                         details={"backupDirectory": str(backup),
                                  "candidateDirectory": str(candidate),
                                  "legacyImported": len(imported),
                                  "caddySha256": ingress_digest})
        except BaseException as failure:
            reason = _receipt_reason(failure)
            try:
                ip_cutover_rollback.rollback(identity, console_url=console_url)
            except BaseException as recovery_failure:
                _record(ledger, outcome="rollback_failed", image_id=inputs.image_id,
                             details={"reason": reason,
                                      "recoveryReason": _receipt_reason(recovery_failure)})
                raise ApplyError("cutover_and_rollback_failed") from recovery_failure
            _record(ledger, outcome="rolled_back", image_id=inputs.image_id,
                         details={"reason": reason,
                                  "backupDirectory": str(backup),
                                  "candidateDirectory": str(candidate)})
            raise ApplyError("cutover_rolled_back") from failure
    return ledger.read()


def preflight_only(inputs: Inputs) -> dict[str, object]:
    """Read-only exact-image, old-pair, network, Caddy and port-pool gate."""
    inputs.validate()
    _require(getattr(os, "geteuid", lambda: -1)() == 0, "root_required")
    config = protected_cutover.load_config(inputs.protected_file)
    with protected_cutover.host_lock():
        old = protected_cutover.preflight(config, source=inputs.source,
                                          revision=inputs.revision,
                                          image_id=inputs.image_id)
        values = _publication_inputs(inputs, config)
        _caddy_source("atom-tls", config.network, values["ATOM_CADDY_IMAGE"])
        _require(not (config.backup_root / ("candidate-" + inputs.revision[:12])).exists()
                 and not (config.state_dir / (inputs.revision + ".identity.json")).exists(),
                 "candidate_already_exists")
    return {"status": "ready", "oldImageId": old["oldImageId"],
            "candidateImageId": inputs.image_id,
            "backupDirectory": old["backupDirectory"],
            "candidateCaddyIp": inputs.candidate_caddy_ip,
            "firstPort": int(values["ATOM_FIRST_PORT"]),
            "lastPort": int(values["ATOM_LAST_PORT"])}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preflight", "rehearse", "apply"))
    parser.add_argument("--protected-config", type=Path, required=True)
    parser.add_argument("--publication-env", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--candidate-caddy-ip", required=True)
    arguments = parser.parse_args(argv)
    try:
        inputs = Inputs(arguments.protected_config, arguments.publication_env,
                        arguments.source, arguments.revision,
                        arguments.image_id, arguments.candidate_caddy_ip)
        result = (preflight_only(inputs) if arguments.mode == "preflight"
                  else apply(inputs, rehearsal=arguments.mode == "rehearse"))
    except (ApplyError, protected_cutover.CutoverError,
            ip_cutover_env.EnvironmentError, ip_cutover_rollback.RollbackError,
            OSError, ValueError, KeyError) as error:
        print(_receipt_reason(error), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
