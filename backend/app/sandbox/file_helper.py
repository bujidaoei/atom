"""Fixed Linux worker program. Standard library only; never accepts source or root."""
import base64
from contextlib import contextmanager
import fnmatch
from functools import lru_cache
import hashlib
import json
import os
from pathlib import PurePosixPath
import re
import signal
import stat
import sys
import unicodedata
import uuid

MAX_FILE = 8 * 1024 * 1024
MAX_INPUT = 50 * 1024 * 1024
MAX_TEXT = 256 * 1024
_RESERVED = {".git", ".pi", "node_modules", "__pycache__"}


class FileError(ValueError):
    pass


def _path(value, *, pattern=False, root=False):
    if root and value == ".":
        return value
    if (not isinstance(value, str) or not value
            or unicodedata.normalize("NFC", value) != value or "\\" in value
            or any(unicodedata.category(c).startswith("C") for c in value)):
        raise FileError("invalid_path")
    if len(value.encode("utf-8")) > 1024:
        raise FileError("invalid_path")
    parts = value.split("/")
    if len(parts) > 32:
        raise FileError("invalid_path")
    for part in parts:
        lowered = part.casefold()
        if (part in {"", ".", ".."} or part[-1:] in {".", " "} or ":" in part
                or lowered in _RESERVED or lowered.startswith(".env")
                or re.fullmatch(r"(?:con|prn|aux|nul|conin\$|conout\$|com[1-9¹²³]|lpt[1-9¹²³])(?:\..*)?", lowered)
                or any(c in part for c in '<>|"') or (not pattern and any(c in part for c in '*?'))):
            raise FileError("invalid_path")
    return value


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise FileError("invalid_operation")


def validate(request):
    if not isinstance(request, dict) or not isinstance(request.get("op"), str):
        raise FileError("invalid_operation")
    schemas = {"read_bytes": {"op", "path"}, "read_lines": {"op", "path", "start", "limit"},
               "glob": {"op", "pattern", "limit"}, "grep": {"op", "pattern", "path", "glob", "case_sensitive", "limit"},
               "write": {"op", "path", "content"}}
    op = request["op"]
    expected = schemas.get(op)
    if expected is None or set(request) != (expected | ({"expected_sha256"} if op == "write" and "expected_sha256" in request else set())):
        raise FileError("invalid_operation")
    if "path" in request:
        _path(request["path"], root=op == "grep")
    if "limit" in request:
        _integer(request["limit"], 1, 5000 if op == "read_lines" else 500)
    if op == "read_lines":
        _integer(request["start"], 1, 10000000)
    if op == "glob":
        _path(request["pattern"], pattern=True)
    if op == "grep":
        if not isinstance(request["pattern"], str) or not 1 <= len(request["pattern"]) <= 2000 or type(request["case_sensitive"]) is not bool:
            raise FileError("invalid_operation")
        if request["glob"] != "":
            _path(request["glob"], pattern=True)
    if op == "write":
        if not isinstance(request["content"], str) or len(request["content"].encode("utf-8")) > MAX_FILE:
            raise FileError("file_too_large")
        digest = request.get("expected_sha256")
        if "expected_sha256" in request and (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise FileError("invalid_operation")
    return request


def _check_alias(parent, name):
    with os.scandir(parent) as entries:
        for count, entry in enumerate(entries, 1):
            if count > 16384:
                raise FileError("entry_limit")
            if entry.name != name and entry.name.casefold() == name.casefold():
                raise FileError("invalid_path")


@contextmanager
def _parent(root, path, *, create=False):
    current = os.dup(root)
    try:
        for part in path.split("/")[:-1]:
            if create:
                _check_alias(current, part)
                try:
                    os.mkdir(part, mode=0o700, dir_fd=current)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            os.close(current)
            current = child
        yield current, path.split("/")[-1]
    finally:
        os.close(current)


def _read(root, path, maximum=MAX_FILE):
    with _parent(root, path) as (parent, name):
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise FileError("unsafe_file")
            if info.st_size > maximum:
                raise FileError("file_too_large")
            data = stream.read(maximum + 1)
            if len(data) > maximum:
                raise FileError("file_too_large")
            return data


def _write(root, request):
    path = request["path"]
    data = request["content"].encode("utf-8")
    with _parent(root, path, create=True) as (parent, name):
        _check_alias(parent, name)
        try:
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            info = None
        if info and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
            raise FileError("unsafe_file")
        if "expected_sha256" in request:
            if info is None or hashlib.sha256(_read(root, path)).hexdigest() != request["expected_sha256"]:
                raise FileError("file_conflict")
        temporary = ".atom-write-" + uuid.uuid4().hex
        created = False
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
            created = True
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
            created = False
        finally:
            if created:
                os.unlink(temporary, dir_fd=parent)
    return {"bytes_written": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _walk(root, prefix=""):
    visited = 0

    def descend(descriptor, prefix):
        nonlocal visited
        with os.scandir(descriptor) as entries:
            names = []
            for entry in entries:
                visited += 1
                if visited > 16384:
                    raise FileError("entry_limit")
                names.append(entry.name)
        for name in sorted(names):
            path = prefix + name
            try:
                _path(path)
            except (FileError, UnicodeError):
                continue
            info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                yield path, False, info.st_size
            elif stat.S_ISDIR(info.st_mode):
                yield path, True, 0
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                try:
                    yield from descend(child, path + "/")
                finally:
                    os.close(child)
    yield from descend(root, prefix)


def _grep_candidates(root, base):
    if base == ".":
        yield from _walk(root)
        return
    with _parent(root, base) as (parent, name):
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
            yield base, False, info.st_size
        elif stat.S_ISDIR(info.st_mode):
            directory = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            try:
                yield from _walk(directory, base + "/")
            finally:
                os.close(directory)
        else:
            raise FileError("unsafe_file")


def _matches(path, pattern):
    parts, patterns = path.split("/"), pattern.split("/")

    @lru_cache(maxsize=None)
    def match(i, j):
        if j == len(patterns):
            return i == len(parts)
        if patterns[j] == "**":
            return match(i, j + 1) or (i < len(parts) and match(i + 1, j))
        return i < len(parts) and fnmatch.fnmatchcase(parts[i], patterns[j]) and match(i + 1, j + 1)
    return match(0, 0)


def _text(lines, empty):
    text = "\n".join(lines) if lines else empty
    if len(text.encode("utf-8")) > MAX_TEXT:
        raise FileError("output_limit")
    return {"text": text}


def execute(request):
    validate(request)
    if not sys.platform.startswith("linux"):
        raise FileError("unsupported_platform")
    root = os.open("/workspace", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        import fcntl
        fcntl.flock(root, fcntl.LOCK_EX)
        op = request["op"]
        if op == "write":
            return _write(root, request)
        if op in {"read_bytes", "read_lines"}:
            data = _read(root, request["path"])
            if op == "read_bytes":
                return {"base64": base64.b64encode(data).decode("ascii"), "sha256": hashlib.sha256(data).hexdigest()}
            lines = data.decode("utf-8", errors="replace").splitlines()
            start = request["start"] - 1
            return _text(lines[start:start + request["limit"]], "(empty range)")
        if op == "glob":
            matches = []
            for path, _directory, _size in _walk(root):
                if _matches(path, request["pattern"]):
                    matches.append(path)
                    if len(matches) == request["limit"]:
                        break
            return _text(sorted(matches), "(no matches)")
        matcher = re.compile(request["pattern"], 0 if request["case_sensitive"] else re.IGNORECASE)
        matches = []
        output_bytes = 0
        for path, directory, size in _grep_candidates(root, request["path"]):
            if directory or size > 1048576:
                continue
            if request["glob"] and not PurePosixPath(path).match(request["glob"]):
                continue
            for number, line in enumerate(_read(root, path, 1048576).decode("utf-8", errors="replace").splitlines(), 1):
                if matcher.search(line):
                    value = f"{path}:{number}:{line}"
                    output_bytes += len(value.encode("utf-8")) + (1 if matches else 0)
                    if output_bytes > MAX_TEXT:
                        raise FileError("output_limit")
                    matches.append(value)
                    if len(matches) == request["limit"]:
                        return _text(matches, "(no matches)")
        return _text(matches, "(no matches)")
    finally:
        os.close(root)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise FileError("invalid_operation")
        result[key] = value
    return result


def _timeout(*_args):
    raise FileError("operation_timeout")


def _nonfinite(_value):
    raise FileError("invalid_operation")


def main():
    try:
        if not sys.platform.startswith("linux"):
            raise FileError("unsupported_platform")
        seconds = int(sys.argv[1])
        _integer(seconds, 1, 10)
        signal.signal(signal.SIGALRM, _timeout)
        signal.setitimer(signal.ITIMER_REAL, seconds)
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise FileError("input_limit")
        request = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_nonfinite)
        result = {"ok": True, "result": execute(request)}
    except FileError as error:
        result = {"ok": False, "error": str(error)}
    except (OSError, ValueError, TypeError, RecursionError):
        result = {"ok": False, "error": "file_operation_failed"}
    finally:
        if sys.platform.startswith("linux"):
            signal.setitimer(signal.ITIMER_REAL, 0)
    sys.stdout.write(json.dumps(result, ensure_ascii=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
