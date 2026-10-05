"""Build root-private candidate environments from the running production pair.

The old pair remains the authority for its existing credentials. COS and verifier
credentials come from independent private files; neither is rendered to stdout.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import subprocess


class EnvironmentError(RuntimeError):
    """A stable failure code which does not include an environment value."""


KEY = re.compile(r"[A-Z][A-Z0-9_]*\Z")
IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
STORAGE_KEYS = frozenset({
    "ATOM_UPLOAD_DIR", "ATOM_STORAGE_BACKEND", "ATOM_STORAGE_S3_ENDPOINT",
    "ATOM_STORAGE_S3_ACCESS_KEY", "ATOM_STORAGE_S3_SECRET_KEY",
    "ATOM_STORAGE_S3_BUCKET", "ATOM_STORAGE_S3_REGION",
    "ATOM_STORAGE_S3_PREFIX", "ATOM_STORAGE_PUBLIC_URL_BASE",
})


def _read_pairs(lines: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in lines:
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if (not separator or KEY.fullmatch(key) is None or key in result
                or any(character in value for character in "\r\n\0")):
            raise EnvironmentError("invalid_environment_line")
        result[key] = value
    return result


def _private_file(path: Path) -> dict[str, str]:
    info = path.stat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
            or stat.S_IMODE(info.st_mode) != 0o600):
        raise EnvironmentError("private_file_permissions")
    return _read_pairs(path.read_text(encoding="utf-8").splitlines())


def _container_env(name: str) -> tuple[dict[str, str], str]:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,80}", name) is None:
        raise EnvironmentError("invalid_container_name")
    command = subprocess.run(
        ["docker", "inspect", name], capture_output=True, text=True, check=False,
    )
    if command.returncode or len(command.stdout) > 1_000_000:
        raise EnvironmentError("container_inspection_failed")
    try:
        data = json.loads(command.stdout)
        container = data[0]
        values = _read_pairs(container["Config"]["Env"])
        image = container["Image"]
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise EnvironmentError("invalid_container_inspection") from exc
    if IMAGE.fullmatch(image) is None:
        raise EnvironmentError("invalid_container_image")
    return values, image


def _write_private(path: Path, values: dict[str, str]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            for key, value in sorted(values.items()):
                if (KEY.fullmatch(key) is None
                        or any(character in value for character in "\r\n\0")):
                    raise EnvironmentError("invalid_environment_value")
                stream.write(f"{key}={value}\n")
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def build(*, old_api: str, old_broker: str, storage_file: Path,
          verifier_file: Path, output_dir: Path, candidate_image: str,
          worker_image: str, seccomp_file: Path, public_ip: str,
          first_port: int, last_port: int) -> tuple[Path, Path]:
    if (os.geteuid() != 0 or IMAGE.fullmatch(candidate_image) is None
            or IMAGE.fullmatch(worker_image) is None):
        raise EnvironmentError("root_and_exact_images_required")
    try:
        canonical = ipaddress.ip_address(public_ip).compressed
    except ValueError as exc:
        raise EnvironmentError("invalid_public_ip") from exc
    if (canonical != public_ip or not 1024 <= first_port < last_port <= 65535
            or last_port - first_port + 1 > 512):
        raise EnvironmentError("invalid_origin_pool")
    directory = output_dir.resolve(strict=True)
    info = directory.stat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise EnvironmentError("private_directory_permissions")
    if any((directory / name).exists() for name in ("api.env", "broker.env")):
        raise EnvironmentError("candidate_environment_exists")
    storage = _private_file(storage_file)
    verifier = _private_file(verifier_file)
    if (set(storage) != STORAGE_KEYS or storage["ATOM_STORAGE_BACKEND"] != "cos"
            or not all(storage[key] for key in STORAGE_KEYS - {"ATOM_STORAGE_PUBLIC_URL_BASE"})
            or set(verifier) != {"ATOM_VERIFIER_CONTROL_TOKEN"}
            or not verifier["ATOM_VERIFIER_CONTROL_TOKEN"]):
        raise EnvironmentError("incomplete_private_environment")
    if not seccomp_file.is_absolute() or not seccomp_file.is_file():
        raise EnvironmentError("missing_seccomp_policy")
    api, old_image = _container_env(old_api)
    broker, broker_image = _container_env(old_broker)
    if old_image != broker_image:
        raise EnvironmentError("old_pair_image_mismatch")
    required = {"ATOM_SECRET", "ATOM_RUNTIME_TOKEN", "ATOM_BROKER_ADMIN_TOKEN",
                "ATOM_BROKER_GRANT_KEY", "ATOM_COMPLETION_GRANT_KEY"}
    if not required.issubset(api) or not api["ATOM_SECRET"]:
        raise EnvironmentError("incomplete_old_api_environment")
    policy_digest = hashlib.sha256(worker_image.encode("ascii") + b"\0"
                                   + seccomp_file.read_bytes()).hexdigest()
    api.update(storage)
    api.update(verifier)
    api.update({
        "ATOM_SESSION_MODE": "durable",
        "ATOM_COOKIE_SECURE": "true",
        "ATOM_COOKIE_PATH": "/",
        "ATOM_CONSOLE_PROOF_REQUIRED": "true",
        "ATOM_CONSOLE_ORIGIN": f"https://{public_ip}",
        "ATOM_IP_PREVIEW_ENABLED": "true",
        "ATOM_IP_PUBLIC_ENABLED": "true",
        "ATOM_IP_PREVIEW_ADDRESS": public_ip,
        "ATOM_IP_PREVIEW_FIRST_PORT": str(first_port),
        "ATOM_IP_PREVIEW_LAST_PORT": str(last_port),
        "ATOM_PUBLICATION_VERIFICATION": "advisory",
        "ATOM_VERIFIER_ORIGIN": "http://atom-verifier:8765",
        "ATOM_VERIFIER_POLICY_DIGEST": policy_digest,
        "ATOM_VERIFIER_RUNNER_VERSION": "atom-verifier-" + worker_image[7:19],
    })
    broker["ATOM_BROKER_IMAGE"] = candidate_image
    api_path, broker_path = directory / "api.env", directory / "broker.env"
    _write_private(api_path, api)
    try:
        _write_private(broker_path, broker)
    except BaseException:
        api_path.unlink(missing_ok=True)
        raise
    return api_path, broker_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("old-api", "old-broker", "storage-file", "verifier-file",
                 "output-dir", "candidate-image", "worker-image", "seccomp-file",
                 "public-ip", "first-port", "last-port"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    try:
        build(old_api=args.old_api, old_broker=args.old_broker,
              storage_file=Path(args.storage_file), verifier_file=Path(args.verifier_file),
              output_dir=Path(args.output_dir), candidate_image=args.candidate_image,
              worker_image=args.worker_image, seccomp_file=Path(args.seccomp_file),
              public_ip=args.public_ip, first_port=int(args.first_port),
              last_port=int(args.last_port))
    except (EnvironmentError, ValueError, OSError) as exc:
        raise SystemExit(type(exc).__name__ if not isinstance(exc, EnvironmentError)
                         else str(exc)) from None
    print("candidate_environment_ready")


if __name__ == "__main__":
    main()
