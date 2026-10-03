"""Private Linux snapshot artifacts; storage acknowledgement is not registration."""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import io
import os
from pathlib import Path
import re
import stat
import sys
import time
import uuid
from typing import Protocol

from .snapshots import MAX_ARCHIVE_BYTES, SnapshotError, verify_snapshot

_KEY = re.compile(r"[a-f0-9]{64}\Z")
_STAGE = re.compile(r"\.stage-[a-f0-9]{32}\Z")


class ArtifactError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Artifact:
    key: str
    revision: str
    size: int


class SnapshotStore(Protocol):
    @property
    def local_root(self) -> Path | None: ...
    def read(self, key: str) -> bytes: ...
    def put(self, payload: bytes) -> Artifact: ...


def configured_artifact_store(settings, local_root: Path) -> SnapshotStore:
    if settings.storage_backend == 'cos':
        from .cos_artifacts import CosArtifactStore
        return CosArtifactStore(settings)
    if settings.storage_backend == 'local':
        return ArtifactStore(local_root)
    raise ArtifactError('invalid_artifact_configuration')


def _describe(payload: bytes) -> Artifact:
    if not isinstance(payload, bytes) or len(payload) > MAX_ARCHIVE_BYTES:
        raise ArtifactError("invalid_artifact")
    try:
        verified = verify_snapshot(io.BytesIO(payload))
    except SnapshotError:
        raise ArtifactError("invalid_artifact") from None
    return Artifact(hashlib.sha256(payload).hexdigest(), verified.revision, len(payload))


class ArtifactStore:
    @property
    def local_root(self) -> Path:
        return self.root

    def __init__(self, root: Path, *, lock_timeout: float = 3, scan_limit: int = 10000):
        if sys.platform != "linux":
            raise ArtifactError("unsupported_artifact_platform")
        if isinstance(lock_timeout, bool) or not isinstance(lock_timeout, (int, float)) or not 0 < lock_timeout <= 10:
            raise ArtifactError("invalid_artifact_configuration")
        if type(scan_limit) is not int or not 2 <= scan_limit <= 100000:
            raise ArtifactError("invalid_artifact_configuration")
        self.root = Path(root)
        if not self.root.is_absolute():
            raise ArtifactError("invalid_artifact_root")
        self._timeout, self._scan_limit = lock_timeout, scan_limit
        with self._locked(exclusive=True) as directory:
            self._recover(directory)

    @contextmanager
    def _locked(self, *, exclusive):
        import fcntl
        directory = None
        try:
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            info = os.fstat(directory)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
                raise ArtifactError("unsafe_artifact_root")
            deadline = time.monotonic() + self._timeout
            while True:
                try:
                    fcntl.flock(directory, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise ArtifactError("artifact_store_busy") from None
                    time.sleep(0.01)
            yield directory
        except OSError:
            raise ArtifactError("artifact_io_error") from None
        finally:
            if directory is not None:
                os.close(directory)

    @staticmethod
    def _safe_file(info, *, links=(1,)):
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink not in links or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077 or info.st_size > MAX_ARCHIVE_BYTES):
            raise ArtifactError("unsafe_artifact_file")

    def _read_file(self, directory, name, *, links=(1,), sync=False):
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            before = os.fstat(descriptor)
            self._safe_file(before, links=links)
            payload = bytearray()
            while chunk := os.read(descriptor, min(65536, MAX_ARCHIVE_BYTES - len(payload) + 1)):
                payload.extend(chunk)
                if len(payload) > MAX_ARCHIVE_BYTES:
                    raise ArtifactError("invalid_artifact")
            after = os.fstat(descriptor)
            signature = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)
            if signature(before) != signature(after) or len(payload) != before.st_size:
                raise ArtifactError("artifact_changed")
            if sync:
                os.fsync(descriptor)
            return bytes(payload), before
        finally:
            os.close(descriptor)

    def _recover(self, directory):
        pending = []
        count = 0
        with os.scandir(directory) as entries:
            for count, entry in enumerate(entries, 1):
                if count > self._scan_limit:
                    raise ArtifactError("artifact_scan_limit")
                if _STAGE.fullmatch(entry.name):
                    pending.append(entry.name)
        for name in pending:
            info = os.stat(name, dir_fd=directory, follow_symlinks=False)
            self._safe_file(info, links=(1, 2))
            if info.st_nlink == 2:
                payload, _ = self._read_file(directory, name, links=(2,))
                artifact = _describe(payload)
                published = os.stat(artifact.key + ".atomsnap", dir_fd=directory, follow_symlinks=False)
                if (published.st_dev, published.st_ino) != (info.st_dev, info.st_ino):
                    raise ArtifactError("unsafe_artifact_stage")
            os.unlink(name, dir_fd=directory)
        if pending:
            os.fsync(directory)
        return count - len(pending)

    def read(self, key: str) -> bytes:
        if not isinstance(key, str) or not _KEY.fullmatch(key):
            raise ArtifactError("invalid_artifact_key")
        with self._locked(exclusive=False) as directory:
            payload, _ = self._read_file(directory, key + ".atomsnap")
            if _describe(payload).key != key:
                raise ArtifactError("artifact_digest_mismatch")
            return payload

    def put(self, payload: bytes) -> Artifact:
        artifact = _describe(payload)
        with self._locked(exclusive=True) as directory:
            count = self._recover(directory)
            name = artifact.key + ".atomsnap"
            try:
                existing, _ = self._read_file(directory, name, sync=True)
            except FileNotFoundError:
                existing = None
            if existing is not None:
                if _describe(existing) != artifact or existing != payload:
                    raise ArtifactError("artifact_digest_mismatch")
                os.fsync(directory)
                return artifact
            if count >= self._scan_limit - 1:
                raise ArtifactError("artifact_capacity")
            stage = ".stage-" + uuid.uuid4().hex
            descriptor = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            try:
                view = memoryview(payload)
                while view:
                    written = os.write(descriptor, view)
                    if written <= 0:
                        raise ArtifactError("artifact_io_error")
                    view = view[written:]
                os.fsync(descriptor)
                os.link(stage, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
            finally:
                os.close(descriptor)
                os.unlink(stage, dir_fd=directory)
                os.fsync(directory)
            return artifact
