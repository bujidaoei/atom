import json
import os
from pathlib import Path
import time
import uuid

import pytest

from app.sandbox.docker_driver import DockerDriver, run_bounded
from app.sandbox.grants import Grant
from app.sandbox.lifecycle import Lifecycle
from app.sandbox.registry import Registry

IMAGE = os.environ.get("ATOM_TEST_DOCKER_IMAGE")
pytestmark = pytest.mark.skipif(not IMAGE, reason="requires explicit pinned local Docker test image")


def test_artifact_component_on_actual_linux(tmp_path):
    root = Path(__file__).resolve().parents[3]
    sources = json.dumps({
        "snapshots": (root / "backend/app/snapshots.py").read_text(encoding="utf-8"),
        "artifacts": (root / "backend/app/artifacts.py").read_text(encoding="utf-8"),
        "tests": (root / "backend/tests/test_snapshot_artifacts.py").read_text(encoding="utf-8"),
    }).encode()
    script = """
import json,sys,types,unittest
sources=json.loads(sys.stdin.buffer.read())
app=types.ModuleType('app');app.__path__=[];sys.modules['app']=app
for name in ('snapshots','artifacts'):
    module=types.ModuleType('app.'+name);sys.modules[module.__name__]=module;setattr(app,name,module)
    exec(compile(sources[name],name+'.py','exec'),module.__dict__)
tests=types.ModuleType('artifact_tests');sys.modules[tests.__name__]=tests
exec(compile(sources['tests'],'test_snapshot_artifacts.py','exec'),tests.__dict__)
result=unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromModule(tests))
print(json.dumps({'tests':result.testsRun,'skipped':len(result.skipped)}))
sys.exit(0 if result.wasSuccessful() else 1)
"""
    registry = Registry(tmp_path / "broker.db")
    driver = DockerDriver(registry.broker_id, IMAGE)
    now = int(time.time())
    grant = Grant("g", "o", "p", "r", "a", 1, "a" * 64, now, now + 120)
    with Lifecycle(registry, driver) as lifecycle:
        lifecycle.start()
        attempt = lifecycle.provision(grant)
        state = driver.inspect(attempt)
        status, out, err = run_bounded([driver.executable, "exec", "-i", state.id, "python3", "-I", "-c", script],
                                       input_data=sources, timeout=25)
        assert status == 0, err.decode("utf-8")
        report = json.loads(out)
        assert report["tests"] == 11 and report["skipped"] == 0
    assert not driver.owned_inventory()


def test_artifact_survives_writer_container_removal():
    root = Path(__file__).resolve().parents[3]
    sources = json.dumps({name: (root / f"backend/app/{name}.py").read_text(encoding="utf-8")
                          for name in ("snapshots", "artifacts")}).encode()
    owner = uuid.uuid4().hex
    volume = "atom-artifact-test-" + owner
    containers = []
    status, out, _ = run_bounded(["docker", "volume", "create", "--label", f"atom.artifact-test={owner}", volume])
    assert status == 0 and out.decode().strip() == volume
    status, out, _ = run_bounded(["docker", "volume", "inspect", volume])
    assert status == 0 and json.loads(out)[0]["Labels"]["atom.artifact-test"] == owner
    loader = """
import json,sys,types,hashlib,struct
from pathlib import Path
sources=json.loads(sys.stdin.buffer.read())
app=types.ModuleType('app');app.__path__=[];sys.modules['app']=app
for name in ('snapshots','artifacts'):
    module=types.ModuleType('app.'+name);sys.modules[module.__name__]=module;setattr(app,name,module)
    exec(compile(sources[name],name+'.py','exec'),module.__dict__)
store=app.artifacts.ArtifactStore(Path('/store'))
manifest=b'{"files":[],"version":1}'
payload=b'ATOMSNAP1\\n'+struct.pack('>I',len(manifest))+manifest
"""
    def execute(script, *, setup=False):
        name = "atom-artifact-test-" + uuid.uuid4().hex
        containers.append(name)
        args = ["docker", "run", "--name", name, "--label", f"atom.artifact-test={owner}",
                "--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
                "--mount", f"type=volume,source={volume},target=/store", "--user", "0:0" if setup else "1000:1000"]
        if setup:
            args += ["--cap-add=CHOWN"]
        status, out, err = run_bounded([*args, "-i", IMAGE, "python3", "-I", "-c", script],
                                       input_data=sources, timeout=25)
        assert status == 0, err.decode()
        # Remove each completed writer before starting a new reader container.
        remove(name)
        return out
    def remove(name):
        status, out, _ = run_bounded(["docker", "inspect", name])
        if status == 0:
            metadata = json.loads(out)[0]
            assert metadata["Config"]["Labels"]["atom.artifact-test"] == owner
            status, _, _ = run_bounded(["docker", "rm", "--force", metadata["Id"]])
            assert status == 0
        elif status != 0:
            status, remaining, _ = run_bounded(["docker", "ps", "-aq", "--filter", f"name=^/{name}$"])
            assert status == 0 and not remaining.strip()
    try:
        execute("import os;os.chmod('/store',0o700);os.chown('/store',1000,1000)", setup=True)
        key = execute(loader + "print(store.put(payload).key)").decode().strip()
        read = execute(loader + "key=hashlib.sha256(payload).hexdigest();assert store.read(key)==payload;print(key)").decode().strip()
        assert read == key
    finally:
        for name in containers:
            remove(name)
        status, out, _ = run_bounded(["docker", "volume", "inspect", volume])
        assert status == 0 and json.loads(out)[0]["Labels"]["atom.artifact-test"] == owner
        status, _, _ = run_bounded(["docker", "volume", "rm", volume])
        assert status == 0
