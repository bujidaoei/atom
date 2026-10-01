from dataclasses import asdict, replace
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import time

import pytest

from app.snapshots import receive_snapshot
from app.sandbox.checkpoints import CheckpointOperations
import app.sandbox.checkpoints as checkpoints
from app.sandbox.docker_driver import DockerDriver, run_bounded
from app.sandbox.grants import Grant
from app.sandbox.lifecycle import Lifecycle, LifecycleError
from app.sandbox.registry import Registry, RegistryError

IMAGE = os.environ.get("ATOM_TEST_DOCKER_IMAGE")
pytestmark = pytest.mark.skipif(not IMAGE, reason="requires explicit pinned local Docker test image")


def archive(files):
    manifest = json.dumps({"version": 1, "files": [
        {"path": path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for path, data in sorted(files.items())]}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return (b"ATOMSNAP1\n" + struct.pack(">I", len(manifest)) + manifest
            + b"".join(data for _, data in sorted(files.items())), hashlib.sha256(manifest).hexdigest())


@pytest.fixture
def environment(tmp_path):
    registry = Registry(tmp_path / "broker.db")
    driver = DockerDriver(registry.broker_id, IMAGE)
    payload, revision = archive({})
    now = int(time.time())
    grant = Grant("g", "o", "p", "r", "a", 1, revision, now, now + 180)
    with Lifecycle(registry, driver) as lifecycle:
        lifecycle.start()
        attempt = lifecycle.provision(grant)
        lifecycle.seed(grant, payload)
        yield registry, driver, lifecycle, grant, attempt
    assert not driver.owned_inventory()


def test_actual_edits_export_reimport_and_quiescing_denies_writes(environment, tmp_path):
    registry, driver, lifecycle, grant, attempt = environment
    content = "verified 中文\n"
    lifecycle.file_operation(grant, attempt.id, "write", "tool", {"op": "write", "path": "nested/app.txt", "content": content})
    exported = lifecycle.export_checkpoint(grant)
    assert exported.attempt_id == attempt.id
    assert registry.find(attempt.id).state == "quiescing"
    assert registry.find(attempt.id).checkpoint_revision is None
    assert lifecycle.export_checkpoint(grant) == exported
    with pytest.raises(RegistryError, match="attempt_not_ready"):
        lifecycle.file_operation(grant, attempt.id, "late", "tool", {"op": "write", "path": "late", "content": "bad"})
    received = receive_snapshot(io.BytesIO(exported.payload), tmp_path)
    assert received.revision == exported.revision
    assert (received.path / "nested/app.txt").read_bytes() == content.encode()
    lifecycle.release(grant, attempt.id)
    next_grant = replace(grant, jti="next", attempt="next", fence=2, base_revision=exported.revision)
    successor = lifecycle.provision(next_grant)
    lifecycle.seed(next_grant, exported.payload)
    result = lifecycle.file_operation(next_grant, successor.id, "read", "tool", {"op": "read_bytes", "path": "nested/app.txt"})
    assert result["data"]["sha256"] == hashlib.sha256(content.encode()).hexdigest()


def test_unmodified_workspace_exports_exact_empty_snapshot(environment):
    registry, driver, lifecycle, grant, attempt = environment
    payload, revision = archive({})
    exported = lifecycle.export_checkpoint(grant)
    assert exported.payload == payload and exported.revision == revision
    assert registry.find(attempt.id).state == "quiescing"


def test_large_binary_export_exceeds_old_output_limit(tmp_path):
    chunk = bytes(range(256)) * (8 * 1024 * 1024 // 256)
    payload, revision = archive({f"file-{i}": chunk for i in range(7)})
    registry = Registry(tmp_path / "broker.db")
    driver = DockerDriver(registry.broker_id, IMAGE)
    now = int(time.time())
    grant = Grant("g", "o", "p", "r", "a", 1, revision, now, now + 180)
    with Lifecycle(registry, driver) as lifecycle:
        lifecycle.start()
        lifecycle.provision(grant)
        lifecycle.seed(grant, payload)
        exported = lifecycle.export_checkpoint(grant)
        assert len(exported.payload) > 50 * 1024 * 1024
        assert exported.payload == payload and exported.revision == revision
    assert not driver.owned_inventory()


def test_unsafe_workspace_export_retires_without_result(environment, caplog):
    registry, driver, lifecycle, grant, attempt = environment
    state = driver.inspect(attempt)
    status, _, _ = run_bounded([driver.executable, "exec", state.id, "python3", "-I", "-c",
                               "import os;os.symlink('/etc/passwd','/workspace/unsafe')"])
    assert status == 0
    with pytest.raises(LifecycleError, match="checkpoint_outcome_unknown"):
        lifecycle.export_checkpoint(grant)
    assert "broker_checkpoint_helper_failed code=unsafe_file_type" in caplog.text
    assert registry.find(attempt.id).state == "terminated"
    assert registry.find(attempt.id).checkpoint_revision is None
    assert driver.inspect(attempt) is None and not lifecycle.ready


def test_revocation_after_actual_export_denies_result(environment, monkeypatch):
    registry, driver, lifecycle, grant, attempt = environment
    original = CheckpointOperations.execute
    def revoked_after_export(self, current):
        result = original(self, current)
        assert result.payload.startswith(b"ATOMSNAP1\n")
        registry.revoke(grant.jti)
        return result
    monkeypatch.setattr(CheckpointOperations, "execute", revoked_after_export)
    with pytest.raises(LifecycleError, match="checkpoint_outcome_unknown"):
        lifecycle.export_checkpoint(grant)
    assert registry.find(attempt.id).checkpoint_revision is None
    assert registry.find(attempt.id).state == "terminated"
    assert driver.inspect(attempt) is None


def test_corrupted_real_export_is_rejected_by_host_verification(environment, monkeypatch):
    registry, driver, lifecycle, grant, attempt = environment
    lifecycle.file_operation(grant, attempt.id, "write", "tool", {"op": "write", "path": "a", "content": "content"})
    original = checkpoints.run_bounded
    def corrupted(*args, **kwargs):
        status, out, err = original(*args, **kwargs)
        assert status == 0 and out.endswith(b"content")
        return status, out[:-1] + b"!", err
    monkeypatch.setattr(checkpoints, "run_bounded", corrupted)
    with pytest.raises(LifecycleError, match="checkpoint_outcome_unknown"):
        lifecycle.export_checkpoint(grant)
    assert registry.find(attempt.id).state == "terminated"
    assert registry.find(attempt.id).checkpoint_revision is None
    assert driver.inspect(attempt) is None


def test_process_death_after_export_never_records_checkpointed(tmp_path):
    registry = Registry(tmp_path / "broker.db")
    driver = DockerDriver(registry.broker_id, IMAGE)
    payload, revision = archive({"a": b"saved input"})
    now = int(time.time())
    grant = Grant("g", "o", "p", "r", "a", 1, revision, now, now + 180)
    script = """
import json,os,sys
from pathlib import Path
from app.sandbox.registry import Registry
from app.sandbox.docker_driver import DockerDriver
from app.sandbox.grants import Grant
from app.sandbox.lifecycle import Lifecycle
from app.sandbox.checkpoints import CheckpointOperations
r=Registry(Path(sys.argv[1]));d=DockerDriver(r.broker_id,sys.argv[2]);l=Lifecycle(r,d)
l.start();g=Grant(**json.loads(sys.argv[3]));a=l.provision(g);l.seed(g,sys.stdin.buffer.read())
print(a.id,flush=True)
original=CheckpointOperations.execute
def interrupted(self,attempt):
    result=original(self,attempt)
    assert result.revision==g.base_revision
    os._exit(37)
CheckpointOperations.execute=interrupted
l.export_checkpoint(g)
"""
    try:
        child = subprocess.run([sys.executable, "-c", script, str(registry.path), IMAGE, json.dumps(asdict(grant))],
            input=payload, capture_output=True, timeout=40, cwd=Path(__file__).resolve().parents[2])
        assert child.returncode == 37, child.stderr
        attempt = registry.find(child.stdout.decode().strip())
        assert attempt.state == "quiescing" and attempt.checkpoint_revision is None
        with Lifecycle(Registry(registry.path), driver) as restarted:
            restarted.start()
            assert registry.find(attempt.id).state == "terminated"
            assert registry.find(attempt.id).checkpoint_revision is None
            assert driver.inspect(attempt) is None
    finally:
        for attempt in registry.unterminated():
            driver.terminate(attempt)
    assert not driver.owned_inventory()


def test_snapshot_component_on_actual_linux(environment):
    registry, driver, lifecycle, grant, attempt = environment
    root = Path(__file__).resolve().parents[3]
    sources = json.dumps({"source": (root / "backend/app/snapshots.py").read_text(encoding="utf-8"),
                          "tests": (root / "backend/tests/test_snapshots.py").read_text(encoding="utf-8")}).encode()
    script = """
import json,sys,types,unittest
sources=json.loads(sys.stdin.buffer.read())
app=types.ModuleType('app');app.__path__=[];sys.modules['app']=app
module=types.ModuleType('app.snapshots');sys.modules[module.__name__]=module;app.snapshots=module
exec(compile(sources['source'],'snapshots.py','exec'),module.__dict__)
tests=types.ModuleType('snapshot_tests');sys.modules[tests.__name__]=tests
exec(compile(sources['tests'],'test_snapshots.py','exec'),tests.__dict__)
result=unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromModule(tests))
print(json.dumps({'tests':result.testsRun,'skipped':[str(item[0]) for item in result.skipped]}))
sys.exit(0 if result.wasSuccessful() else 1)
"""
    state = driver.inspect(attempt)
    status, out, err = run_bounded([driver.executable, "exec", "-i", state.id, "python3", "-I", "-c", script],
                                   input_data=sources, timeout=25)
    assert status == 0, err.decode("utf-8")
    report = json.loads(out)
    assert report["tests"] >= 20
    assert len(report["skipped"]) == 1 and "unsupported_export" in report["skipped"][0]
