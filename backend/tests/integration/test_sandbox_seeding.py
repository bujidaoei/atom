from dataclasses import asdict, replace
import hashlib
import json
import os
import struct
import time
import subprocess
import sys
from pathlib import Path

import pytest

from app.sandbox.docker_driver import DockerDriver, run_bounded
from app.sandbox.grants import Grant
from app.sandbox.lifecycle import Lifecycle, LifecycleError
from app.sandbox.registry import Registry, RegistryError

IMAGE = os.environ.get("ATOM_TEST_DOCKER_IMAGE")
pytestmark = pytest.mark.skipif(not IMAGE, reason="requires explicit pinned local Docker test image")


def archive(files):
    entries = [{"path": path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
               for path, data in sorted(files.items())]
    manifest = json.dumps({"version": 1, "files": entries}, ensure_ascii=False,
                          sort_keys=True, separators=(",", ":")).encode("utf-8")
    return (b"ATOMSNAP1\n" + struct.pack(">I", len(manifest)) + manifest
            + b"".join(data for _, data in sorted(files.items())), hashlib.sha256(manifest).hexdigest())


@pytest.fixture
def environment(tmp_path):
    registry = Registry(tmp_path / "broker.db")
    driver = DockerDriver(registry.broker_id, IMAGE)
    lifecycle = Lifecycle(registry, driver)
    lifecycle.start()
    now = int(time.time())
    grant = Grant("g", "o", "p", "r", "a", 1, "a" * 64, now, now + 180)
    try:
        yield registry, driver, lifecycle, grant
    finally:
        lifecycle.close()
        assert not driver.owned_inventory()


@pytest.mark.parametrize("files", [{}, {"nested/中文.txt": "真实项目\n".encode(), "binary.bin": bytes(range(256))}])
def test_seed_real_bytes_then_authorized_file_operation(environment, files):
    registry, driver, lifecycle, grant = environment
    payload, revision = archive(files)
    grant = replace(grant, base_revision=revision)
    attempt = lifecycle.provision(grant)
    with pytest.raises(RegistryError, match="attempt_not_ready"):
        lifecycle.file_operation(grant, attempt.id, "early", "tool", {"op": "glob", "pattern": "**", "limit": 100})
    ready = lifecycle.seed(grant, payload)
    assert ready.state == "ready" and ready.base_revision == revision
    for index, (path, content) in enumerate(files.items()):
        result = lifecycle.file_operation(grant, ready.id, f"read-{index}", "tool", {"op": "read_bytes", "path": path})
        assert result["data"]["sha256"] == hashlib.sha256(content).hexdigest()
    with pytest.raises(LifecycleError, match="attempt_not_provisioning"):
        lifecycle.seed(grant, payload)
    assert driver.inspect(ready).running


@pytest.mark.parametrize("failure", ["revision", "digest", "truncated", "trailing", "path"])
def test_bad_seed_never_admits_ready_and_retires_worker(environment, failure):
    registry, driver, lifecycle, grant = environment
    payload, revision = archive({"../outside" if failure == "path" else "a.txt": b"content"})
    grant = replace(grant, base_revision="f" * 64 if failure == "revision" else revision)
    if failure == "digest":
        payload = payload[:-1] + b"!"
    elif failure == "truncated":
        payload = payload[:-1]
    elif failure == "trailing":
        payload += b"!"
    attempt = lifecycle.provision(grant)
    with pytest.raises(LifecycleError, match="seed_outcome_unknown"):
        lifecycle.seed(grant, payload)
    assert registry.find(attempt.id).state == "terminated"
    assert driver.inspect(attempt) is None
    assert not lifecycle.ready


def test_nonempty_workspace_cannot_be_merged(environment, caplog):
    registry, driver, lifecycle, grant = environment
    payload, revision = archive({"a.txt": b"content"})
    grant = replace(grant, base_revision=revision)
    attempt = lifecycle.provision(grant)
    container = driver.inspect(attempt)
    status, _, _ = run_bounded([driver.executable, "exec", container.id, "python3", "-I", "-c",
                               "from pathlib import Path;Path('/workspace/existing').write_bytes(b'original')"])
    assert status == 0
    with pytest.raises(LifecycleError, match="seed_outcome_unknown"):
        lifecycle.seed(grant, payload)
    assert "broker_seed_helper_failed code=workspace_not_empty" in caplog.text
    assert registry.find(attempt.id).state == "terminated"


def test_ready_commit_failure_after_real_seed_retires_worker(environment, monkeypatch):
    registry, driver, lifecycle, grant = environment
    payload, revision = archive({"a.txt": b"content"})
    grant = replace(grant, base_revision=revision)
    attempt = lifecycle.provision(grant)
    def fail_commit(*args):
        container = driver.inspect(attempt)
        status, out, _ = run_bounded([driver.executable, "exec", container.id, "python3", "-I", "-c",
                                     "from pathlib import Path;print(Path('/workspace/a.txt').read_text())"])
        assert status == 0 and out.strip() == b"content"
        raise RegistryError("registry_unavailable")
    monkeypatch.setattr(registry, "transition", fail_commit)
    with pytest.raises(LifecycleError, match="seed_outcome_unknown"):
        lifecycle.seed(grant, payload)
    assert registry.find(attempt.id).state == "terminated"
    assert driver.inspect(attempt) is None


def test_large_binary_seed_uses_snapshot_bound(environment):
    registry, driver, lifecycle, grant = environment
    chunk = bytes(range(256)) * (8 * 1024 * 1024 // 256)
    payload, revision = archive({f"file-{i}": chunk for i in range(7)})
    assert len(payload) > 50 * 1024 * 1024
    grant = replace(grant, base_revision=revision)
    lifecycle.provision(grant)
    attempt = lifecycle.seed(grant, payload)
    container = driver.inspect(attempt)
    status, out, _ = run_bounded([driver.executable, "exec", container.id, "python3", "-I", "-c",
        "from pathlib import Path;import hashlib,json;print(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('/workspace').iterdir()}))"])
    assert status == 0
    assert json.loads(out) == {f"file-{i}": hashlib.sha256(chunk).hexdigest() for i in range(7)}


def test_process_death_after_seed_requires_new_attempt(tmp_path):
    registry = Registry(tmp_path / "broker.db")
    driver = DockerDriver(registry.broker_id, IMAGE)
    payload, revision = archive({"a.txt": b"content"})
    now = int(time.time())
    grant = Grant("g", "o", "p", "r", "a", 1, revision, now, now + 180)
    script = """
import json,os,sys
from pathlib import Path
from app.sandbox.registry import Registry
from app.sandbox.docker_driver import DockerDriver
from app.sandbox.grants import Grant
from app.sandbox.lifecycle import Lifecycle
r=Registry(Path(sys.argv[1]));d=DockerDriver(r.broker_id,sys.argv[2]);l=Lifecycle(r,d)
l.start();g=Grant(**json.loads(sys.argv[3]));a=l.provision(g)
print(a.id,flush=True)
r.transition=lambda *args: os._exit(31)
l.seed(g,sys.stdin.buffer.read())
"""
    try:
        child = subprocess.run([sys.executable, "-c", script, str(registry.path), IMAGE, json.dumps(asdict(grant))],
            input=payload, capture_output=True, timeout=35, cwd=Path(__file__).resolve().parents[2])
        assert child.returncode == 31, child.stderr
        attempt = registry.find(child.stdout.decode().strip())
        assert attempt.state == "provisioning"
        container = driver.inspect(attempt)
        status, out, _ = run_bounded([driver.executable, "exec", container.id, "python3", "-I", "-c",
                                      "from pathlib import Path;print(Path('/workspace/a.txt').read_text())"])
        assert status == 0 and out.strip() == b"content"
        with Lifecycle(Registry(registry.path), driver) as restarted:
            restarted.start()
            assert registry.find(attempt.id).state == "terminated"
            assert driver.inspect(attempt) is None
            with pytest.raises(RegistryError, match="grant_revoked"):
                restarted.provision(grant)
    finally:
        for attempt in registry.unterminated():
            driver.terminate(attempt)
        assert not driver.owned_inventory()
