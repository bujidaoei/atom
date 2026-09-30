"""Trusted snapshot import into a provisioning container; no caller-selected source."""
from pathlib import Path
import json
import time

from .docker_driver import DockerDriver, DriverError, run_bounded
from .registry import Attempt

MAX_SEED_BYTES = 65 * 1024 * 1024 + 13
_SNAPSHOT_SOURCE = Path(__file__).parents[1].joinpath("snapshots.py").read_text(encoding="utf-8")
_ENTRY = r'''
import fcntl, signal

def _deadline(_signum, _frame):
    raise SnapshotError("seed_timeout")

signal.signal(signal.SIGALRM, _deadline)
signal.alarm(20)
try:
    root = Path("/workspace")
    lock = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if any(root.iterdir()):
            raise SnapshotError("workspace_not_empty")
        received = receive_snapshot(sys.stdin.buffer, root)
        if received.revision != sys.argv[1]:
            raise SnapshotError("seed_revision_mismatch")
        for child in received.path.iterdir():
            child.rename(root / child.name)
        received.path.rmdir()
        os.fsync(lock)
        print(json.dumps({"revision": received.revision}), flush=True)
    finally:
        os.close(lock)
except (SnapshotError, OSError):
    sys.exit(2)
finally:
    signal.alarm(0)
'''


class SeedOperations:
    def __init__(self, driver: DockerDriver):
        self.driver = driver

    def execute(self, attempt: Attempt, payload: bytes) -> None:
        if not isinstance(payload, bytes) or len(payload) > MAX_SEED_BYTES:
            raise DriverError("invalid_seed_input")
        if attempt.state != "provisioning" or attempt.deadline <= time.time():
            raise DriverError("attempt_not_provisioning")
        state = self.driver.inspect(attempt)
        if state is None or not state.running or state.paused:
            raise DriverError("container_not_running")
        status, out, _ = run_bounded(
            [self.driver.executable, "container", "exec", "--interactive", state.id,
             "/usr/local/bin/python3", "-I", "-c", _SNAPSHOT_SOURCE + _ENTRY, attempt.base_revision],
            input_data=payload, timeout=25, output_limit=4096)
        if status != 0:
            raise DriverError("seed_execution_unknown")
        try:
            response = json.loads(out)
        except (ValueError, TypeError):
            raise DriverError("invalid_seed_response") from None
        if response != {"revision": attempt.base_revision}:
            raise DriverError("invalid_seed_response")
