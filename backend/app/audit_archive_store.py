"""Private Linux no-overwrite audit objects; acknowledgement is not ledger registration."""
from contextlib import contextmanager
from dataclasses import dataclass
import math
import os
from pathlib import Path
import re
import stat
import sys
import time
import uuid

from .audit_archive import MAX_ARCHIVE_BYTES, ArchiveError, decode_archive


@dataclass(frozen=True)
class StoredArchive:
    sha256: str
    size: int


class AuditArchiveStore:
    def __init__(self, root, *, lock_timeout=3, max_entries=10000):
        if sys.platform != 'linux':
            raise ArchiveError('unsupported_archive_platform')
        if (type(lock_timeout) not in (int, float) or not math.isfinite(lock_timeout) or not 0 < lock_timeout <= 10 or
                type(max_entries) is not int or not 2 <= max_entries <= 100000):
            raise ArchiveError('invalid_archive_store_configuration')
        self.root = Path(root)
        if not self.root.is_absolute():
            raise ArchiveError('invalid_archive_store_root')
        self.lock_timeout, self.max_entries = lock_timeout, max_entries
        with self._directory() as directory:
            self._recover(directory)

    @contextmanager
    def _directory(self):
        import fcntl
        directory = None
        try:
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            info = os.fstat(directory)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
                raise ArchiveError('unsafe_archive_root')
            deadline = time.monotonic() + self.lock_timeout
            while True:
                try:
                    fcntl.flock(directory, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise ArchiveError('archive_store_busy') from None
                    time.sleep(.01)
            yield directory
        except OSError:
            raise ArchiveError('archive_store_io_error') from None
        finally:
            if directory is not None:
                os.close(directory)

    @staticmethod
    def _file(info, links=(1,)):
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                info.st_nlink not in links or stat.S_IMODE(info.st_mode) & 0o077 or
                not 0 <= info.st_size <= MAX_ARCHIVE_BYTES):
            raise ArchiveError('unsafe_archive_file')

    def _read(self, directory, name, *, links=(1,), sync=False):
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            before = os.fstat(descriptor)
            self._file(before, links)
            payload = bytearray()
            while chunk := os.read(descriptor, min(65536, MAX_ARCHIVE_BYTES-len(payload)+1)):
                payload.extend(chunk)
                if len(payload) > MAX_ARCHIVE_BYTES:
                    raise ArchiveError('archive_capacity')
            after = os.fstat(descriptor)
            signature = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns, value.st_nlink)
            if signature(before) != signature(after) or len(payload) != before.st_size:
                raise ArchiveError('archive_changed')
            if sync:
                os.fsync(descriptor)
            return bytes(payload), before
        finally:
            os.close(descriptor)

    def _recover(self, directory):
        stages, count = [], 0
        with os.scandir(directory) as entries:
            for count, entry in enumerate(entries, 1):
                if count > self.max_entries:
                    raise ArchiveError('archive_store_capacity')
                if re.fullmatch(r'\.stage-[0-9a-f]{32}', entry.name):
                    stages.append(entry.name)
                elif not re.fullmatch(r'[0-9a-f]{64}\.atomaudit', entry.name):
                    raise ArchiveError('unexpected_archive_entry')
        for stage in stages:
            info = os.stat(stage, dir_fd=directory, follow_symlinks=False)
            self._file(info, (1, 2))
            if info.st_nlink == 2:
                import hashlib
                payload, _ = self._read(directory, stage, links=(2,))
                digest = hashlib.sha256(payload).hexdigest()
                decode_archive(payload, expected_sha256=digest)
                published = os.stat(digest+'.atomaudit', dir_fd=directory, follow_symlinks=False)
                if (published.st_dev, published.st_ino) != (info.st_dev, info.st_ino):
                    raise ArchiveError('unsafe_archive_stage')
            os.unlink(stage, dir_fd=directory)
        if stages:
            os.fsync(directory)
        return count-len(stages)

    def read(self, *, expected_sha256):
        if not isinstance(expected_sha256, str) or not re.fullmatch('[0-9a-f]{64}', expected_sha256):
            raise ArchiveError('invalid_archive_key')
        with self._directory() as directory:
            self._recover(directory)
            payload, _ = self._read(directory, expected_sha256+'.atomaudit')
            decode_archive(payload, expected_sha256=expected_sha256)
            return payload

    def put(self, payload, *, expected_sha256):
        decode_archive(payload, expected_sha256=expected_sha256)
        result = StoredArchive(expected_sha256, len(payload))
        with self._directory() as directory:
            count = self._recover(directory)
            name = expected_sha256+'.atomaudit'
            try:
                existing, _ = self._read(directory, name, sync=True)
            except FileNotFoundError:
                existing = None
            if existing is not None:
                if existing != payload:
                    raise ArchiveError('archive_digest_mismatch')
                os.fsync(directory)
                return result
            if count >= self.max_entries-1:
                raise ArchiveError('archive_store_capacity')
            stage = '.stage-'+uuid.uuid4().hex
            descriptor = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            try:
                view = memoryview(payload)
                while view:
                    written = os.write(descriptor, view)
                    if written <= 0:
                        raise ArchiveError('archive_store_io_error')
                    view = view[written:]
                os.fchmod(descriptor, 0o400)
                os.fsync(descriptor)
                os.link(stage, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
            finally:
                os.close(descriptor)
                os.unlink(stage, dir_fd=directory)
                os.fsync(directory)
            return result
