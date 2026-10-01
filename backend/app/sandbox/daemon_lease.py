"""Docker-daemon-wide broker ownership, independent of copied registry files."""
from __future__ import annotations

import json
import hashlib
import re
import subprocess
import time
import uuid

from .docker_driver import DriverError, run_bounded


_IDENTITY = re.compile(r"[0-9a-f]{32}\Z")
_IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")


class DaemonLeaseError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class _DaemonIdentityLease:
    """An attached, auto-removed Docker container holds one daemon identity.

    The daemon arbitrates its fixed name. Its stdin belongs only to this process;
    owner process death closes that pipe, ends /bin/cat and removes the lease.
    It has no network, host mounts, secrets or Docker socket.
    """

    def __init__(self, identity: str, image: str, *, namespace: str,
                 executable: str = "docker"):
        if namespace not in ("broker", "verifier-coordinator"):
            raise DaemonLeaseError("invalid_daemon_lease_namespace")
        if not isinstance(identity, str) or not _IDENTITY.fullmatch(identity):
            raise DaemonLeaseError("invalid_daemon_identity")
        if not isinstance(image, str) or not _IMAGE.fullmatch(image):
            raise DaemonLeaseError("image_not_pinned")
        if not isinstance(executable, str) or not executable:
            raise DaemonLeaseError("invalid_docker_executable")
        self.name = f"atom-{namespace}-lease-{identity}"
        self._namespace = namespace
        self._owner_label = f"atom.{namespace}-lease.owner"
        self.image = image
        self.executable = executable
        self._owner = uuid.uuid4().hex
        self._process: subprocess.Popen | None = None

    @property
    def alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _inspect(self) -> tuple[str, bool, str] | None:
        try:
            status, output, _ = run_bounded(
                [self.executable, "container", "inspect", self.name, "--format",
                 '{{json .Name}}|{{json .State.Running}}|{{json (index .Config.Labels "' + self._owner_label + '")}}'],
                timeout=3, output_limit=1024)
        except DriverError:
            raise DaemonLeaseError("daemon_lease_inspection_failed") from None
        if status != 0:
            return None
        try:
            fields = output.decode("utf-8").strip().split("|")
            if len(fields) != 3:
                raise ValueError
            name, running, owner = (json.loads(field) for field in fields)
            if name != "/" + self.name or type(running) is not bool or not isinstance(owner, str):
                raise ValueError
            return name, running, owner
        except (ValueError, TypeError, UnicodeError):
            raise DaemonLeaseError("daemon_lease_inspection_failed") from None

    def acquire(self) -> None:
        if self._process is not None:
            raise DaemonLeaseError("daemon_lease_already_started")
        args = [self.executable, "run", "--rm", "-i", "--name", self.name,
                "--label", self._owner_label + "=" + self._owner,
                "--network", "none", "--read-only", "--no-healthcheck", "--pull", "never",
                "--cap-drop", "ALL",
                "--pids-limit", "16", "--memory", "32m", "--cpus", "0.1",
                "--security-opt", "no-new-privileges", "--entrypoint", "/bin/cat",
                self.image]
        try:
            self._process = subprocess.Popen(args, stdin=subprocess.PIPE,
                                             stdout=subprocess.DEVNULL,
                                             stderr=subprocess.DEVNULL)
        except OSError:
            raise DaemonLeaseError("daemon_lease_unavailable") from None
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                observed = self._inspect()
                if observed is not None:
                    if observed[2] != self._owner:
                        raise DaemonLeaseError(self._namespace.replace("-", "_") + "_identity_in_use")
                    if observed[1] and self.alive:
                        return
                if not self.alive:
                    raise DaemonLeaseError("daemon_lease_unavailable")
                time.sleep(0.1)
            raise DaemonLeaseError("daemon_lease_timeout")
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                raise DaemonLeaseError("daemon_lease_release_unknown") from None
        observed = self._inspect()
        if observed is not None and observed[2] == self._owner:
            raise DaemonLeaseError("daemon_lease_release_unknown")


class BrokerDaemonLease(_DaemonIdentityLease):
    def __init__(self, broker_id: str, image: str, *, executable: str = "docker"):
        if not isinstance(broker_id, str) or not _IDENTITY.fullmatch(broker_id):
            raise DaemonLeaseError("invalid_broker_identity")
        super().__init__(broker_id, image, namespace="broker", executable=executable)


class VerifierCoordinatorLease(_DaemonIdentityLease):
    """The same daemon arbitrates every process using one verifier identity."""

    def __init__(self, verifier_id: str, image: str, *, executable: str = "docker"):
        if (not isinstance(verifier_id, str) or not verifier_id
                or len(verifier_id) > 128 or
                re.fullmatch(r"[A-Za-z0-9_.-]+", verifier_id) is None):
            raise DaemonLeaseError("invalid_verifier_identity")
        identity = hashlib.sha256(b"atom-verifier-coordinator-v1\0" +
                                  verifier_id.encode("ascii")).hexdigest()[:32]
        super().__init__(identity, image, namespace="verifier-coordinator",
                         executable=executable)
