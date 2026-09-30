import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
import time

import pytest

from app.sandbox.docker_driver import DockerDriver
from app.sandbox.file_helper import FileError
from app.sandbox.file_ops import FileOperations
from app.sandbox.grants import Grant
from app.sandbox.registry import Registry

IMAGE = os.environ.get("ATOM_TEST_DOCKER_IMAGE")
pytestmark = pytest.mark.skipif(not IMAGE, reason="requires explicit pinned local Docker test image")


@pytest.fixture
def worker(tmp_path):
    registry = Registry(tmp_path / "broker.db")
    driver = DockerDriver(registry.broker_id, IMAGE)
    now = int(time.time())
    grant = Grant("g", "o", "p", "r", "a", 1, "a" * 64, now, now + 90)
    admitted = registry.admit(grant)
    provisioning = registry.transition(grant, admitted.version, "provisioning")
    driver.ensure(provisioning)
    # Component fixture explicitly seeds an empty ready worker. This is not
    # production revision import/registration acceptance.
    ready = registry.transition(grant, provisioning.version, "ready")
    try:
        yield driver, ready, FileOperations(driver)
    finally:
        driver.terminate(ready)
        assert driver.owned_inventory() == []


def test_real_utf8_binary_ranges_glob_and_grep(worker):
    driver, attempt, files = worker
    content = "你好\r\nBeta\nthird\n"
    saved = files.execute(attempt, {"op": "write", "path": "src/a.txt", "content": content})
    assert saved["bytes_written"] == len(content.encode())
    assert saved["sha256"] == hashlib.sha256(content.encode()).hexdigest()
    raw = files.execute(attempt, {"op": "read_bytes", "path": "src/a.txt"})
    assert base64.b64decode(raw["base64"]) == content.encode()
    assert files.execute(attempt, {"op": "read_lines", "path": "src/a.txt", "start": 2, "limit": 1})["text"] == "Beta"
    assert files.execute(attempt, {"op": "read_lines", "path": "src/a.txt", "start": 20, "limit": 1})["text"] == "(empty range)"
    assert files.execute(attempt, {"op": "glob", "pattern": "**/*.txt", "limit": 10})["text"] == "src/a.txt"
    assert files.execute(attempt, {"op": "glob", "pattern": "*.txt", "limit": 10})["text"] == "(no matches)"
    assert files.execute(attempt, {"op": "grep", "pattern": "beta", "path": "src", "glob": "*.txt", "case_sensitive": False, "limit": 10})["text"] == "src/a.txt:2:Beta"
    data = b"\x00\xff\xfe\x01"
    driver._run("container", "exec", driver.inspect(attempt).id, "/usr/local/bin/python3", "-c",
                "from pathlib import Path;Path('/workspace/raw').write_bytes(bytes([0,255,254,1]))")
    assert base64.b64decode(files.execute(attempt, {"op": "read_bytes", "path": "raw"})["base64"]) == data


def test_actual_symlink_hardlink_fifo_and_traversal_refusal(worker):
    driver, attempt, files = worker
    driver._run("container", "exec", driver.inspect(attempt).id, "/usr/local/bin/python3", "-c",
        "import os;from pathlib import Path;Path('/tmp/canary').write_text('outside');"
        "os.symlink('/tmp','/workspace/link');os.symlink('/tmp/canary','/workspace/filelink');"
        "Path('/workspace/original').write_text('original');os.link('/workspace/original','/workspace/hard');"
        "os.mkfifo('/workspace/fifo')")
    for path in ("../tmp/canary", "link/canary", "filelink", "hard", "fifo"):
        with pytest.raises(FileError):
            files.execute(attempt, {"op": "read_bytes", "path": path})
        with pytest.raises(FileError):
            files.execute(attempt, {"op": "write", "path": path, "content": "changed"})
    assert driver._run("container", "exec", driver.inspect(attempt).id, "/usr/local/bin/python3", "-c",
        "from pathlib import Path;print(Path('/tmp/canary').read_text());print(Path('/workspace/original').read_text())").decode().splitlines() == ["outside", "original"]


def test_competing_compare_and_swap_writes_do_not_lose_updates(worker):
    _driver, attempt, files = worker
    saved = files.execute(attempt, {"op": "write", "path": "x", "content": "original"})
    def write(content):
        try:
            files.execute(attempt, {"op": "write", "path": "x", "content": content, "expected_sha256": saved["sha256"]})
            return content
        except FileError as error:
            assert str(error) == "file_conflict"
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, ["first", "second"]))
    winner = [value for value in results if value is not None]
    assert len(winner) == 1
    assert base64.b64decode(files.execute(attempt, {"op": "read_bytes", "path": "x"})["base64"]).decode() == winner[0]


def test_large_stdin_output_limits_and_regex_deadline(worker):
    driver, attempt, files = worker
    content = "x" * (8 * 1048576)
    saved = files.execute(attempt, {"op": "write", "path": "large", "content": content})
    assert saved["bytes_written"] == 8 * 1048576
    assert len(base64.b64decode(files.execute(attempt, {"op": "read_bytes", "path": "large"})["base64"])) == 8 * 1048576
    with pytest.raises(FileError, match="output_limit"):
        files.execute(attempt, {"op": "read_lines", "path": "large", "start": 1, "limit": 1})
    files.execute(attempt, {"op": "write", "path": "regex", "content": "a" * 20000 + "!"})
    started = time.monotonic()
    with pytest.raises(FileError, match="operation_timeout"):
        files.execute(attempt, {"op": "grep", "pattern": "(a+)+$", "path": "regex", "glob": "", "case_sensitive": True, "limit": 1}, timeout_seconds=1)
    assert time.monotonic() - started < 5
    assert driver.inspect(attempt).running
    assert files.execute(attempt, {"op": "read_lines", "path": "regex", "start": 2, "limit": 1})["text"] == "(empty range)"


def test_aliases_and_failed_disk_write_preserve_original(worker):
    driver, attempt, files = worker
    files.execute(attempt, {"op": "write", "path": "Dir/original", "content": "preserve"})
    for path in ("dir/other", "Dir/ORIGINAL"):
        with pytest.raises(FileError, match="file_operation_failed|invalid_path"):
            files.execute(attempt, {"op": "write", "path": path, "content": "conflict"})
    driver._run("container", "exec", driver.inspect(attempt).id, "/usr/local/bin/python3", "-c",
        "import os;f=open('/workspace/fill','wb');remaining=os.statvfs('/workspace').f_bavail*os.statvfs('/workspace').f_frsize;"
        "f.write(b'x'*(remaining-4096));f.close()")
    with pytest.raises(FileError, match="file_operation_failed"):
        files.execute(attempt, {"op": "write", "path": "Dir/original", "content": "x" * 1048576})
    assert base64.b64decode(files.execute(attempt, {"op": "read_bytes", "path": "Dir/original"})["base64"]) == b"preserve"
    assert driver._run("container", "exec", driver.inspect(attempt).id, "/usr/local/bin/python3", "-c",
        "from pathlib import Path;print(len(list(Path('/workspace/Dir').glob('.atom-write-*'))))").strip() == b"0"
