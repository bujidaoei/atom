"""Bounded verified export; no implicit storage or revision registration."""
from dataclasses import dataclass, field
import io
import logging
from pathlib import Path
import re
import time

from ..snapshots import MAX_ARCHIVE_BYTES, verify_snapshot
from .docker_driver import DockerDriver, DriverError, run_bounded
from .registry import Attempt

_SOURCE = Path(__file__).parents[1].joinpath("snapshots.py").read_text(encoding="utf-8")
_LOG = logging.getLogger('atom.sandbox.checkpoints')
_REASON = re.compile(rb'checkpoint_failure:([a-z_]{1,64})\Z')


def _failure_class(diagnostic: bytes) -> str:
    for line in diagnostic.splitlines():
        if match := _REASON.fullmatch(line):
            return match.group(1).decode('ascii')
    if b'OCI runtime exec failed' in diagnostic or b'Error response from daemon' in diagnostic:
        return 'docker_exec_error'
    if b'Cannot connect to the Docker daemon' in diagnostic or b'context canceled' in diagnostic:
        return 'docker_transport_error'
    if b'Traceback (most recent call last)' in diagnostic:
        return 'python_exception'
    return 'empty_stderr' if not diagnostic else 'unclassified_stderr'
_ENTRY = r'''
import fcntl,signal
def _deadline(_signum,_frame):
    raise SnapshotError("export_timeout")
signal.signal(signal.SIGALRM,_deadline)
signal.alarm(20)
try:
    root=Path("/workspace")
    lock=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        fcntl.flock(lock,fcntl.LOCK_EX)
        export_snapshot(root,sys.stdout.buffer)
        sys.stdout.buffer.flush()
    finally:
        os.close(lock)
except SnapshotError as error:
    print('checkpoint_failure:' + error.code, file=sys.stderr)
    sys.exit(2)
except OSError:
    print('checkpoint_failure:io_error', file=sys.stderr)
    sys.exit(2)
finally:
    signal.alarm(0)
'''


@dataclass(frozen=True)
class CheckpointExport:
    attempt_id: str
    attempt_version: int
    revision: str
    payload: bytes = field(repr=False)


class CheckpointOperations:
    def __init__(self, driver: DockerDriver):
        self.driver = driver

    def execute(self, attempt: Attempt) -> CheckpointExport:
        if attempt.state != "quiescing" or attempt.deadline <= time.time():
            raise DriverError("attempt_not_quiescing")
        state = self.driver.inspect(attempt)
        if state is None or not state.running or state.paused:
            raise DriverError("container_not_running")
        status, out, diagnostic = run_bounded(
            [self.driver.executable, "container", "exec", state.id, "/usr/local/bin/python3", "-I", "-c", _SOURCE + _ENTRY],
            timeout=25, output_limit=MAX_ARCHIVE_BYTES)
        if status != 0:
            _LOG.warning('broker_checkpoint_helper_failed code=%s status=%d stderr_bytes=%d stdout_bytes=%d',
                         _failure_class(diagnostic), status, len(diagnostic), len(out))
            raise DriverError("checkpoint_export_unknown")
        verified = verify_snapshot(io.BytesIO(out))
        return CheckpointExport(attempt.id, attempt.version, verified.revision, out)
