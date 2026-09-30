"""Verified workspace transfer; independent of the API and runtime lifecycle.

Export requires a frozen Linux source. Receive requires a private, trusted parent.
Callers own stream deadlines, authentication, retention and revision registration.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, fields
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import sys
import tempfile
from typing import BinaryIO, Iterator
import unicodedata
import uuid

_MAGIC = b"ATOMSNAP1\n"
_CHUNK = 64 * 1024
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_DEVICE = re.compile(r"(?:con|conin\$|conout\$|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])(?:\..*)?\Z", re.I)
_EXCLUDED = {".git", ".pi", "node_modules", "__pycache__"}


class SnapshotError(ValueError):
    """Stable safe reason; never includes untrusted names or contents."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Limits:
    max_files: int = 4096
    max_entries: int = 16384
    max_file_bytes: int = 8 * 1024 * 1024
    max_total_bytes: int = 64 * 1024 * 1024
    max_manifest_bytes: int = 1024 * 1024
    max_path_bytes: int = 1024
    max_depth: int = 32

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if type(value) is not int or not 0 < value < 2**31:
                raise ValueError("invalid_snapshot_limits")


@dataclass(frozen=True)
class Entry:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class ReceivedSnapshot:
    revision: str
    files: tuple[Entry, ...]
    path: Path


def _excluded(parts: list[str]) -> bool:
    return any(part.casefold() in _EXCLUDED or part.casefold().startswith(".env") for part in parts)


def _path(value: object, limits: Limits) -> list[str]:
    if not isinstance(value, str) or not value or unicodedata.normalize("NFC", value) != value:
        raise SnapshotError("invalid_path")
    if any(unicodedata.category(char).startswith("C") or char in '\\:<>"|?*' for char in value):
        raise SnapshotError("invalid_path")
    parts = value.split("/")
    if any(not part or part in {".", ".."} or part[-1] in " ." or _DEVICE.fullmatch(part) for part in parts):
        raise SnapshotError("invalid_path")
    if len(value.encode("utf-8")) > limits.max_path_bytes or len(parts) > limits.max_depth:
        raise SnapshotError("limit_exceeded")
    if _excluded(parts):
        raise SnapshotError("excluded_path")
    return parts


def _canonical(entries: tuple[Entry, ...]) -> bytes:
    return json.dumps({"version": 1, "files": [asdict(entry) for entry in entries]},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _validate(entries: tuple[Entry, ...], limits: Limits) -> bytes:
    if len(entries) > limits.max_files:
        raise SnapshotError("limit_exceeded")
    prefixes: dict[str, str] = {}
    file_paths: set[str] = set()
    directory_paths: set[str] = set()
    total = 0
    previous = None
    for entry in entries:
        parts = _path(entry.path, limits)
        if type(entry.size) is not int or entry.size < 0 or not isinstance(entry.sha256, str) or not _DIGEST.fullmatch(entry.sha256):
            raise SnapshotError("invalid_manifest")
        total += entry.size
        if entry.size > limits.max_file_bytes or total > limits.max_total_bytes:
            raise SnapshotError("limit_exceeded")
        if previous is not None and entry.path <= previous:
            raise SnapshotError("path_conflict")
        previous = entry.path
        for count in range(1, len(parts) + 1):
            prefix = "/".join(parts[:count])
            folded = prefix.casefold()
            if folded in prefixes and prefixes[folded] != prefix:
                raise SnapshotError("path_conflict")
            prefixes[folded] = prefix
            (file_paths if count == len(parts) else directory_paths).add(folded)
        if len(prefixes) > limits.max_entries:
            raise SnapshotError("limit_exceeded")
    if file_paths & directory_paths:
        raise SnapshotError("path_conflict")
    encoded = _canonical(entries)
    if len(encoded) > limits.max_manifest_bytes:
        raise SnapshotError("limit_exceeded")
    return encoded


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SnapshotError("invalid_manifest")
        result[key] = value
    return result


def _invalid_constant(_value):
    raise SnapshotError("invalid_manifest")


def _parse(raw: bytes, limits: Limits) -> tuple[tuple[Entry, ...], bytes]:
    try:
        obj = json.loads(raw.decode("utf-8"), object_pairs_hook=_object, parse_constant=_invalid_constant)
    except (ValueError, RecursionError):
        raise SnapshotError("invalid_manifest") from None
    if not isinstance(obj, dict) or set(obj) != {"version", "files"} or type(obj["version"]) is not int or obj["version"] != 1:
        raise SnapshotError("invalid_manifest")
    if not isinstance(obj["files"], list):
        raise SnapshotError("invalid_manifest")
    if len(obj["files"]) > limits.max_files:
        raise SnapshotError("limit_exceeded")
    entries = []
    for item in obj["files"]:
        if not isinstance(item, dict) or set(item) != {"path", "size", "sha256"}:
            raise SnapshotError("invalid_manifest")
        entries.append(Entry(**item))
    frozen = tuple(entries)
    return frozen, _validate(frozen, limits)


def _read(stream: BinaryIO, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = stream.read(min(size - len(chunks), _CHUNK))
        if not isinstance(chunk, bytes) or not chunk or len(chunk) > size - len(chunks):
            raise SnapshotError("truncated_stream")
        chunks.extend(chunk)
    return bytes(chunks)


def _write(stream: BinaryIO, data: bytes) -> None:
    remaining = memoryview(data)
    while remaining:
        count = stream.write(remaining)
        if type(count) is not int or not 0 < count <= len(remaining):
            raise SnapshotError("io_error")
        remaining = remaining[count:]


def receive_snapshot(stream: BinaryIO, parent: Path, limits: Limits = Limits()) -> ReceivedSnapshot:
    """Verify into a new directory; never replace existing work or register a revision."""
    staging = None
    try:
        if _read(stream, len(_MAGIC)) != _MAGIC:
            raise SnapshotError("invalid_magic")
        length = struct.unpack(">I", _read(stream, 4))[0]
        if length > limits.max_manifest_bytes:
            raise SnapshotError("limit_exceeded")
        entries, canonical = _parse(_read(stream, length), limits)
        parent = Path(parent)
        if parent.is_symlink() or not parent.is_dir():
            raise SnapshotError("invalid_parent")
        staging = Path(tempfile.mkdtemp(prefix=".snapshot-", dir=parent))
        for entry in entries:
            destination = staging.joinpath(*entry.path.split("/"))
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            digest = hashlib.sha256()
            with destination.open("xb") as output:
                remaining = entry.size
                while remaining:
                    chunk = _read(stream, min(remaining, _CHUNK))
                    digest.update(chunk)
                    _write(output, chunk)
                    remaining -= len(chunk)
                output.flush()
                os.fsync(output.fileno())
            if digest.hexdigest() != entry.sha256:
                raise SnapshotError("digest_mismatch")
        if stream.read(1) != b"":
            raise SnapshotError("trailing_data")
        completed = parent / ("snapshot-" + uuid.uuid4().hex)
        # The parent is service-private; no untrusted actor can create this name.
        if completed.exists():
            raise SnapshotError("destination_exists")
        staging.rename(completed)
        staging = None
        return ReceivedSnapshot(hashlib.sha256(canonical).hexdigest(), entries, completed)
    except OSError:
        raise SnapshotError("io_error") from None
    finally:
        if staging is not None:
            try:
                shutil.rmtree(staging)
            except OSError:
                raise SnapshotError("cleanup_failed") from None


@contextmanager
def _open_file(root_fd: int, path: str) -> Iterator[int]:
    """Resolve every component relative to an already trusted directory descriptor."""
    directory = os.dup(root_fd)
    file_fd = None
    try:
        parts = path.split("/")
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        info = os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise SnapshotError("unsafe_file_type")
        yield file_fd
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(directory)


def _file_digest(fd: int, limits: Limits, output: BinaryIO | None = None, expected: Entry | None = None) -> tuple[int, str]:
    before = os.fstat(fd)
    if before.st_size > limits.max_file_bytes:
        raise SnapshotError("limit_exceeded")
    size = 0
    digest = hashlib.sha256()
    while True:
        # One extra byte detects growth without reading an unbounded source.
        chunk = os.read(fd, min(_CHUNK, limits.max_file_bytes - size + 1))
        if not chunk:
            break
        size += len(chunk)
        if size > limits.max_file_bytes:
            raise SnapshotError("limit_exceeded")
        if expected is not None and size > expected.size:
            raise SnapshotError("source_changed")
        digest.update(chunk)
        if output is not None:
            _write(output, chunk)
    after = os.fstat(fd)
    signature = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)
    if signature(before) != signature(after) or size != before.st_size:
        raise SnapshotError("source_changed")
    value = digest.hexdigest()
    if expected is not None and (size != expected.size or value != expected.sha256):
        raise SnapshotError("source_changed")
    return size, value


def export_snapshot(root: Path, stream: BinaryIO, limits: Limits = Limits()) -> str:
    """Stream a quiescent Linux workspace. Failure can leave an invalid partial stream."""
    if sys.platform != "linux":
        raise SnapshotError("unsupported_platform")
    root_fd = None
    try:
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        entries: list[Entry] = []
        visited = 0
        total = 0

        def walk(directory: int, prefix: str):
            nonlocal visited, total
            with os.scandir(directory) as children:
                for child in children:
                    visited += 1
                    if visited > limits.max_entries:
                        raise SnapshotError("limit_exceeded")
                    if _excluded([child.name]):
                        continue
                    relative = prefix + child.name
                    _path(relative, limits)
                    info = child.stat(follow_symlinks=False)
                    if stat.S_ISDIR(info.st_mode):
                        nested = os.open(child.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                        try:
                            walk(nested, relative + "/")
                        finally:
                            os.close(nested)
                    elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                        if len(entries) >= limits.max_files or total + info.st_size > limits.max_total_bytes:
                            raise SnapshotError("limit_exceeded")
                        with _open_file(root_fd, relative) as fd:
                            current = os.fstat(fd)
                            if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                                raise SnapshotError("source_changed")
                            size, digest = _file_digest(fd, limits)
                        total += size
                        if total > limits.max_total_bytes:
                            raise SnapshotError("limit_exceeded")
                        entries.append(Entry(relative, size, digest))
                    else:
                        raise SnapshotError("unsafe_file_type")

        walk(root_fd, "")
        frozen = tuple(sorted(entries, key=lambda entry: entry.path))
        canonical = _validate(frozen, limits)
        _write(stream, _MAGIC + struct.pack(">I", len(canonical)) + canonical)
        for entry in frozen:
            with _open_file(root_fd, entry.path) as fd:
                _file_digest(fd, limits, stream, entry)
        return hashlib.sha256(canonical).hexdigest()
    except OSError:
        raise SnapshotError("io_error") from None
    finally:
        if root_fd is not None:
            os.close(root_fd)
