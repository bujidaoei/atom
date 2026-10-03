"""Durable exact-generation identity before forward maintenance begins.

This root-private receipt is written before changing ingress or a writer. It
retains the old Caddy bytes and six container IDs for crash recovery. It is
not a license to restore an older generation after successor writes: recovery
must separately apply the post-exposure logical write fence.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import stat

import ip_cutover_rollback
import protected_cutover


ROLES = ("api", "broker", "preview", "public", "verifier", "caddy")
SUPPORT_NAMES = {"preview": "atom-preview", "public": "atom-public",
                 "verifier": "atom-verifier", "caddy": "atom-tls"}
PINNED_ROLES = ("api", "preview", "public", "caddy")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
FORMAT = 1
MAX_FILE = 3 * 1024 * 1024


class IdentityError(RuntimeError):
    """Stable, credential-free forward identity failure code."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise IdentityError(code)


def _name(config: protected_cutover.CutoverConfig, role: str) -> str:
    return config.api if role == "api" else config.broker if role == "broker" \
        else SUPPORT_NAMES[role]


def _bytes_record(payload: bytes) -> dict[str, str]:
    _require(type(payload) is bytes and 0 < len(payload) <= 1024 * 1024,
             "invalid_forward_caddy_bytes")
    return {"sha256": hashlib.sha256(payload).hexdigest(),
            "base64": base64.b64encode(payload).decode("ascii")}


def _pinned_address(item: dict, network_name: str) -> str:
    network = (item.get("NetworkSettings", {}).get("Networks", {})
               .get(network_name, {}))
    address = network.get("IPAddress")
    pinned = (network.get("IPAMConfig") or {}).get("IPv4Address")
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError as exc:
        raise IdentityError("forward_service_ip_invalid") from exc
    _require(parsed.version == 4 and parsed.compressed == address
             and pinned == address, "forward_service_ip_unpinned")
    return address


def _decode_bytes(value: object) -> bytes:
    _require(type(value) is dict and set(value) == {"sha256", "base64"}
             and type(value["sha256"]) is str
             and HEX64.fullmatch(value["sha256"]) is not None
             and type(value["base64"]) is str, "invalid_forward_caddy_receipt")
    try:
        payload = base64.b64decode(value["base64"], validate=True)
    except (ValueError, binascii.Error) as exc:
        raise IdentityError("invalid_forward_caddy_receipt") from exc
    _require(0 < len(payload) <= 1024 * 1024
             and base64.b64encode(payload).decode("ascii") == value["base64"]
             and hashlib.sha256(payload).hexdigest() == value["sha256"],
             "invalid_forward_caddy_receipt")
    return payload


def _private_parent(path: Path) -> None:
    _require(path.is_absolute() and ".." not in path.parts, "invalid_forward_identity_path")
    try:
        protected_cutover._trusted_parents(path)
        info = path.parent.lstat()
    except (OSError, protected_cutover.CutoverError) as exc:
        raise IdentityError("forward_identity_parent_unavailable") from exc
    _require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0
             and stat.S_IMODE(info.st_mode) == 0o700,
             "insecure_forward_identity_parent")


def _record(config: protected_cutover.CutoverConfig,
            active: dict[str, object], successor_revision: str,
            successor_image: str) -> dict[str, object]:
    _require(type(active) is dict
             and type(active.get("revision")) is str
             and protected_cutover.REVISION.fullmatch(active["revision"]) is not None
             and protected_cutover.REVISION.fullmatch(successor_revision) is not None
             and active["revision"] != successor_revision
             and type(active.get("imageId")) is str
             and protected_cutover.IMAGE.fullmatch(active["imageId"]) is not None
             and protected_cutover.IMAGE.fullmatch(successor_image) is not None
             and active["imageId"] != successor_image
             and type(active.get("successor")) is dict
             and active["successor"] == {"revision": successor_revision,
                                         "imageId": successor_image},
             "invalid_forward_generation")
    _require(type(active.get("candidateDirectory")) is str,
             "forward_source_identity_mismatch")
    source = Path(active["candidateDirectory"])
    expected_sources = {
        config.backup_root / (prefix + active["revision"][:12])
        for prefix in ("candidate-", "forward-candidate-")}
    _require(source in expected_sources and source.is_absolute()
             and type(active.get("containerIds")) is dict
             and set(active["containerIds"]) == set(ROLES),
             "forward_source_identity_mismatch")
    ids = active["containerIds"]
    _require(all(type(ids[role]) is str and HEX64.fullmatch(ids[role]) is not None
                 for role in ROLES), "forward_source_identity_mismatch")
    held = {role: _name(config, role) + "-forward-" + active["revision"][:7]
            for role in ROLES}
    _require(len(set(held.values())) == len(held)
             and all(ip_cutover_rollback.NAME.fullmatch(name) is not None
                     for name in held.values()), "invalid_forward_held_names")
    service_ips: dict[str, str] = {}
    for role in ROLES:
        name = _name(config, role)
        item = protected_cutover._inspect(config.docker, "container", name)
        _require(item.get("Name") == "/" + name and item.get("Id") == ids[role]
                 and item.get("State", {}).get("Running") is True,
                 "forward_live_identity_changed")
        _require(ip_cutover_rollback._inspect(held[role]) is None,
                 "forward_held_name_occupied")
        if role in PINNED_ROLES:
            service_ips[role] = _pinned_address(item, config.network)
    _require(len(set(service_ips.values())) == len(PINNED_ROLES),
             "forward_service_ip_collision")
    directory = source / "caddy"
    try:
        protected_cutover._trusted_parents(directory)
        info = directory.lstat()
        _require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0
                 and stat.S_IMODE(info.st_mode) == 0o700,
                 "insecure_forward_caddy_directory")
        contents = {}
        for label, filename in (("base", "Caddyfile.base"),
                                ("active", "Caddyfile")):
            path = directory / filename
            file_info = path.lstat()
            _require(stat.S_ISREG(file_info.st_mode) and file_info.st_uid == 0
                     and stat.S_IMODE(file_info.st_mode) == 0o600
                     and 0 < file_info.st_size <= 1024 * 1024,
                     "insecure_forward_caddy_file")
            contents[label] = _bytes_record(path.read_bytes())
    except (OSError, protected_cutover.CutoverError) as exc:
        raise IdentityError("forward_caddy_unavailable") from exc
    _require(contents["active"]["sha256"] == active.get("caddySha256"),
             "forward_caddy_changed")
    return {"format": FORMAT, "sourceRevision": active["revision"],
            "successorRevision": successor_revision,
            "sourceImageId": active["imageId"],
            "successorImageId": successor_image,
            "sourceDirectory": str(source),
            "backupDirectory": str(config.backup_root /
                                   ("forward-pre-" + successor_revision[:12])),
            "candidateDirectory": str(config.backup_root /
                                      ("forward-candidate-" + successor_revision[:12])),
            "containerIds": ids, "heldNames": held, "serviceIps": service_ips,
            "caddy": contents}


def capture(config: protected_cutover.CutoverConfig, active: dict[str, object],
            successor_revision: str, successor_image: str) -> Path:
    """Write and fsync exact recovery identity before any service mutation."""
    _require(getattr(os, "geteuid", lambda: -1)() == 0, "root_required")
    _require(type(successor_revision) is str
             and protected_cutover.REVISION.fullmatch(successor_revision) is not None,
             "invalid_forward_generation")
    path = config.state_dir / (successor_revision + ".forward.json")
    _private_parent(path)
    _require(not path.exists() and not path.is_symlink(),
             "forward_identity_exists")
    record = _record(config, active, successor_revision, successor_image)
    payload = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
    _require(len(payload) <= MAX_FILE, "forward_identity_too_large")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        read(path, config=config, successor_revision=successor_revision)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


def read(path: Path, *, config: protected_cutover.CutoverConfig,
         successor_revision: str) -> dict[str, object]:
    """Validate a durable receipt before recovery uses any saved identity."""
    _require(type(successor_revision) is str
             and protected_cutover.REVISION.fullmatch(successor_revision) is not None,
             "invalid_forward_generation")
    _private_parent(path)
    _require(path == config.state_dir / (successor_revision + ".forward.json"),
             "forward_identity_path_mismatch")
    try:
        info = path.lstat()
        _require(stat.S_ISREG(info.st_mode) and info.st_uid == 0
                 and stat.S_IMODE(info.st_mode) == 0o600 and info.st_size <= MAX_FILE,
                 "insecure_forward_identity")
        record = json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise IdentityError("forward_identity_unavailable") from exc
    _require(type(record) is dict and set(record) == {
        "format", "sourceRevision", "successorRevision", "sourceImageId",
        "successorImageId", "sourceDirectory", "backupDirectory",
        "candidateDirectory", "containerIds", "heldNames", "serviceIps",
        "caddy"}
        and record["format"] == FORMAT
        and record["successorRevision"] == successor_revision
        and type(record["sourceRevision"]) is str
        and protected_cutover.REVISION.fullmatch(record["sourceRevision"]) is not None
        and record["sourceRevision"] != successor_revision
        and all(type(record[key]) is str
                and protected_cutover.IMAGE.fullmatch(record[key]) is not None
                for key in ("sourceImageId", "successorImageId"))
        and record["sourceImageId"] != record["successorImageId"]
        and type(record["containerIds"]) is dict
        and set(record["containerIds"]) == set(ROLES)
        and all(type(item) is str and HEX64.fullmatch(item) is not None
                for item in record["containerIds"].values())
        and type(record["heldNames"]) is dict
        and record["heldNames"] == {
            role: _name(config, role) + "-forward-" + record["sourceRevision"][:7]
            for role in ROLES}
        and type(record["serviceIps"]) is dict
        and set(record["serviceIps"]) == set(PINNED_ROLES)
        and all(type(record["serviceIps"][role]) is str
                for role in PINNED_ROLES)
        and record["sourceDirectory"] in {
            str(config.backup_root / (prefix + record["sourceRevision"][:12]))
            for prefix in ("candidate-", "forward-candidate-")}
        and record["backupDirectory"] == str(config.backup_root /
                                              ("forward-pre-" + successor_revision[:12]))
        and record["candidateDirectory"] == str(config.backup_root /
                                                 ("forward-candidate-" + successor_revision[:12]))
        and type(record["caddy"]) is dict
        and set(record["caddy"]) == {"base", "active"},
        "invalid_forward_identity")
    try:
        addresses = [ipaddress.ip_address(record["serviceIps"][role])
                     for role in PINNED_ROLES]
    except ValueError as exc:
        raise IdentityError("invalid_forward_service_ips") from exc
    _require(all(address.version == 4 and address.compressed
                 == record["serviceIps"][role]
                 for role, address in zip(PINNED_ROLES, addresses))
             and len(set(addresses)) == len(addresses),
             "invalid_forward_service_ips")
    _decode_bytes(record["caddy"]["base"])
    _decode_bytes(record["caddy"]["active"])
    return record


def caddy_bytes(record: dict[str, object], label: str) -> bytes:
    _require(label in ("base", "active") and type(record) is dict
             and type(record.get("caddy")) is dict,
             "invalid_forward_caddy_receipt")
    return _decode_bytes(record["caddy"].get(label))
