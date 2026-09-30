"""Trusted fixed-profile Docker control; no workload-selected flags or shell API."""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
import hashlib
import json
import re
import time

from .registry import Attempt

_ID = re.compile(r"[0-9a-f]{32}\Z")
_IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_CONTAINER = re.compile(r"[0-9a-f]{64}\Z")
_LIFETIME = "import sys,time;time.sleep(max(0,min(7200,int(sys.argv[1])-time.time())))"


class DriverError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


async def _bounded(args: list[str], timeout: float, output_limit: int) -> tuple[int, bytes, bytes]:
    process = None
    tasks = []
    completion = None
    overflow = False
    try:
        process = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.DEVNULL,
                                                       stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)

        async def read(stream):
            nonlocal overflow
            output = bytearray()
            while chunk := await stream.read(4096):
                if len(output) + len(chunk) > output_limit:
                    overflow = True
                    if process.returncode is None:
                        try:
                            process.kill()
                        except ProcessLookupError:
                            pass
                if not overflow:
                    output.extend(chunk)
            return bytes(output)

        tasks = [asyncio.create_task(read(process.stdout)), asyncio.create_task(read(process.stderr)),
                 asyncio.create_task(process.wait())]
        completion = asyncio.gather(*tasks)
        stdout, stderr, status = await asyncio.wait_for(asyncio.shield(completion), timeout)
        if overflow:
            raise DriverError("driver_output_limit")
        return status, stdout, stderr
    except TimeoutError:
        raise DriverError("driver_timeout") from None
    except OSError:
        raise DriverError("docker_unavailable") from None
    finally:
        if process is not None and process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        if completion is not None and not completion.done():
            try:
                # Keep both readers alive through termination: a stopped reader
                # can leave pipe backpressure preventing process.wait completion.
                await asyncio.wait_for(asyncio.shield(completion), 2)
            except TimeoutError:
                completion.cancel()
                raise DriverError("driver_process_termination_unknown") from None
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


def run_bounded(args: list[str], *, timeout: float = 15, output_limit: int = 256 * 1024) -> tuple[int, bytes, bytes]:
    """Synchronous broker worker-thread helper. CLI termination is not container termination."""
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 30:
        raise DriverError("invalid_driver_timeout")
    if type(output_limit) is not int or not 1 <= output_limit <= 1024 * 1024:
        raise DriverError("invalid_driver_output_limit")
    return asyncio.run(_bounded(args, timeout, output_limit))


@dataclass(frozen=True)
class FileProfile:
    memory_bytes: int = 256 * 1024 * 1024
    workspace_bytes: int = 64 * 1024 * 1024
    temporary_bytes: int = 8 * 1024 * 1024
    nano_cpus: int = 500_000_000
    pids: int = 64

    def __post_init__(self):
        for value, minimum, maximum in (
            (self.memory_bytes, 64 * 1024 * 1024, 2**30),
            (self.workspace_bytes, 1024 * 1024, 256 * 1024 * 1024),
            (self.temporary_bytes, 1024 * 1024, 64 * 1024 * 1024),
            (self.nano_cpus, 100_000_000, 4_000_000_000), (self.pids, 16, 256),
        ):
            if type(value) is not int or not minimum <= value <= maximum:
                raise DriverError("invalid_profile")
        if self.workspace_bytes + self.temporary_bytes >= self.memory_bytes:
            raise DriverError("invalid_profile")

    def mounts(self) -> dict[str, str]:
        return {path: f"rw,nosuid,nodev,size={size},uid=1000,gid=1000,mode=0700"
                for path, size in (("/workspace", self.workspace_bytes), ("/tmp", self.temporary_bytes))}


@dataclass(frozen=True)
class ContainerState:
    id: str
    status: str
    running: bool
    paused: bool
    exit_code: int


@dataclass(frozen=True)
class OwnedContainer:
    id: str
    attempt_id: str


class DockerDriver:
    def __init__(self, broker_id: str, image: str, *, profile: FileProfile = FileProfile(), executable: str = "docker"):
        if not isinstance(broker_id, str) or not _ID.fullmatch(broker_id):
            raise DriverError("invalid_broker_identity")
        if not isinstance(image, str) or not _IMAGE.fullmatch(image):
            raise DriverError("image_not_pinned")
        self.broker_id, self.image, self.profile, self.executable = broker_id, image, profile, executable
        policy = json.dumps({"image": image, "profile": asdict(profile)}, sort_keys=True, separators=(",", ":"))
        self.policy_digest = hashlib.sha256(policy.encode()).hexdigest()

    def _run(self, *arguments: str) -> bytes:
        status, stdout, _stderr = run_bounded([self.executable, *arguments])
        if status != 0:
            raise DriverError("docker_command_failed")
        return stdout

    def owned_inventory(self) -> list[OwnedContainer]:
        output = self._run("container", "ls", "--all", "--no-trunc", "--filter",
                           f"label=atom.broker={self.broker_id}", "--format", "{{json .}}")
        try:
            inventory = []
            for line in output.decode("utf-8").splitlines():
                row = json.loads(line)
                match = re.fullmatch(r"atom-sbox-" + self.broker_id[:12] + r"-([0-9a-f]{32})", row["Names"])
                if not match or not _CONTAINER.fullmatch(row["ID"]):
                    raise DriverError("ownership_mismatch")
                inventory.append(OwnedContainer(row["ID"], match[1]))
            return inventory
        except (ValueError, TypeError, KeyError):
            raise DriverError("invalid_docker_response") from None

    def _name(self, attempt: Attempt) -> str:
        expected = f"atom-sbox-{self.broker_id[:12]}-{attempt.id}"
        if not isinstance(attempt.id, str) or not _ID.fullmatch(attempt.id) or attempt.container_name != expected:
            raise DriverError("ownership_mismatch")
        if not isinstance(attempt.grant_fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", attempt.grant_fingerprint):
            raise DriverError("ownership_mismatch")
        if type(attempt.deadline) is not int or attempt.deadline <= 0:
            raise DriverError("invalid_deadline")
        return expected

    def _labels(self, attempt: Attempt) -> dict[str, str]:
        return {"atom.broker": self.broker_id, "atom.attempt": attempt.id,
                "atom.grant": attempt.grant_fingerprint, "atom.deadline": str(attempt.deadline),
                "atom.profile": "files-v1", "atom.policy": self.policy_digest}

    def _environment(self) -> list[str]:
        # Only the approved content-addressed image defines these values. Never
        # use docker --env NAME, which can copy a value from the broker process.
        try:
            image = json.loads(self._run("image", "inspect", self.image))
            if len(image) != 1 or image[0]["Id"] != self.image:
                raise DriverError("invalid_image_configuration")
            if image[0]["Config"].get("Volumes"):
                raise DriverError("unsupported_image_volumes")
            values = image[0]["Config"].get("Env") or []
            if not isinstance(values, list) or any(not isinstance(value, str) or "=" not in value for value in values):
                raise DriverError("invalid_image_configuration")
            return values
        except (ValueError, KeyError, TypeError):
            raise DriverError("invalid_image_configuration") from None

    def _present(self, name: str) -> bool:
        output = self._run("container", "ls", "--all", "--filter", f"name=^/{name}$", "--format", "{{.Names}}")
        try:
            names = output.decode("utf-8").splitlines()
        except UnicodeError:
            raise DriverError("invalid_docker_response") from None
        if names not in ([], [name]):
            raise DriverError("invalid_docker_response")
        return bool(names)

    def inspect(self, attempt: Attempt) -> ContainerState | None:
        return self._inspect(attempt, enforce_profile=True)

    def _inspect(self, attempt: Attempt, *, enforce_profile: bool) -> ContainerState | None:
        name = self._name(attempt)
        if not self._present(name):
            return None
        try:
            obj = json.loads(self._run("container", "inspect", name))
            if not isinstance(obj, list) or len(obj) != 1:
                raise DriverError("invalid_docker_response")
            record = obj[0]
            config, host, state = record["Config"], record["HostConfig"], record["State"]
            expected = self._labels(attempt)
            if not enforce_profile:
                expected.pop("atom.policy")
            if record["Name"] != "/" + name or any(config["Labels"].get(key) != value for key, value in expected.items()):
                raise DriverError("ownership_mismatch")
            matches = not enforce_profile or (
                record["Name"] == "/" + name and record["Image"] == self.image
                and config["User"] == "1000:1000" and config["WorkingDir"] == "/workspace"
                and config["Cmd"] == ["/usr/local/bin/python3", "-c", _LIFETIME, str(attempt.deadline)]
                and not config.get("Entrypoint") and (config.get("Env") or []) == self._environment()
                and config.get("Healthcheck", {}).get("Test") == ["NONE"]
                and host["NetworkMode"] == "none" and host["ReadonlyRootfs"] is True
                and host["Privileged"] is False and not host.get("Binds") and not record.get("Mounts")
                and not host.get("PortBindings") and not host.get("CapAdd")
                and host["CapDrop"] == ["ALL"] and "no-new-privileges" in host["SecurityOpt"]
                and host["Memory"] == self.profile.memory_bytes and host["MemorySwap"] == self.profile.memory_bytes
                and host["NanoCpus"] == self.profile.nano_cpus and host["PidsLimit"] == self.profile.pids
                and host["Tmpfs"] == self.profile.mounts()
                and host["RestartPolicy"]["Name"] == "no"
            )
            if not matches:
                raise DriverError("profile_mismatch")
            if not isinstance(record["Id"], str) or not _CONTAINER.fullmatch(record["Id"]):
                raise DriverError("invalid_docker_response")
            if type(state["Running"]) is not bool or type(state["Paused"]) is not bool or type(state["ExitCode"]) is not int:
                raise DriverError("invalid_docker_response")
            if state["Status"] not in {"created", "running", "paused", "restarting", "removing", "exited", "dead"}:
                raise DriverError("invalid_docker_response")
            return ContainerState(record["Id"], state["Status"], state["Running"], state["Paused"], state["ExitCode"])
        except (ValueError, KeyError, TypeError, AttributeError):
            raise DriverError("invalid_docker_response") from None

    def ensure(self, attempt: Attempt) -> ContainerState:
        name = self._name(attempt)
        if attempt.state not in {"intent", "provisioning", "ready"}:
            raise DriverError("attempt_not_provisionable")
        remaining = attempt.deadline - time.time()
        if not 0 < remaining <= 7200:
            raise DriverError("invalid_deadline")
        state = self.inspect(attempt)
        if state is None:
            if attempt.state == "ready":
                raise DriverError("container_missing")
            self._environment()
            arguments = ["container", "create", "--pull=never", "--name", name,
                         "--network=none", "--read-only", "--user", "1000:1000", "--entrypoint", "",
                         "--cap-drop=ALL", "--security-opt=no-new-privileges", "--restart=no", "--no-healthcheck",
                         "--memory", str(self.profile.memory_bytes), "--memory-swap", str(self.profile.memory_bytes),
                         "--cpus", str(self.profile.nano_cpus / 1_000_000_000), "--pids-limit", str(self.profile.pids),
                         "--workdir", "/workspace"]
            for path, options in self.profile.mounts().items():
                arguments.extend(["--tmpfs", f"{path}:{options}"])
            for key, value in self._labels(attempt).items():
                arguments.extend(["--label", f"{key}={value}"])
            arguments.extend([self.image, "/usr/local/bin/python3", "-c", _LIFETIME, str(attempt.deadline)])
            self._run(*arguments)
            state = self.inspect(attempt)
        if state is None:
            raise DriverError("creation_unconfirmed")
        if state.status == "created":
            self._run("container", "start", state.id)
            state = self.inspect(attempt)
        if state is None or not state.running or state.paused:
            raise DriverError("container_not_running")
        return state

    def terminate(self, attempt: Attempt) -> None:
        # Policy upgrades must not prevent stopping a previously owned worker.
        # Ownership is still checked, but old limits/image need not match new ones.
        state = self._inspect(attempt, enforce_profile=False)
        if state is None:
            return
        try:
            self._run("container", "rm", "--force", state.id)
        except DriverError:
            if self._inspect(attempt, enforce_profile=False) is not None:
                raise
        if self._present(self._name(attempt)):
            raise DriverError("termination_unconfirmed")
