"""Real tmpfs transfer ordering experiment; not broker/runtime acceptance.

Uses the actual snapshot component, a local image, no host mounts or credentials.
Only controlled synchronous writes occur; this does not prove arbitrary writers quiescent.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.snapshots import receive_snapshot  # noqa: E402


def run(*args: str, data: bytes | None = None, check: bool = True):
    return subprocess.run(args, input=data, capture_output=True, timeout=20, check=check)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="Already available local Python image")
    args = parser.parse_args()
    image = run("docker", "image", "inspect", args.image, "--format", "{{.Id}}").stdout.decode().strip()
    name = "atom-snapshot-probe-" + uuid.uuid4().hex
    owner = uuid.uuid4().hex
    source = base64.b64encode((ROOT / "backend/app/snapshots.py").read_bytes()).decode("ascii")
    loader = (
        "import base64,sys,types;from pathlib import Path;"
        "module=types.ModuleType('atom_snapshot');sys.modules[module.__name__]=module;"
        f"exec(base64.b64decode({source!r}),module.__dict__);"
    )

    def execute(code: str, data: bytes | None = None):
        return run("docker", "exec", "-i", name, "python3", "-c", code, data=data)

    report = {"scope": "controlled-tmpfs-snapshot-lifecycle-only", "image": image}
    try:
        run("docker", "run", "-d", "--pull=never", "--name", name,
            "--label", f"atom.snapshot-probe={owner}", "--network=none", "--read-only",
            "--user", "1000:1000", "--cap-drop=ALL", "--security-opt=no-new-privileges",
            "--memory=128m", "--memory-swap=128m", "--cpus=0.5", "--pids-limit=32",
            "--tmpfs", "/workspace:rw,nosuid,nodev,size=8m,uid=1000,gid=1000,mode=0700",
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=8m,uid=1000,gid=1000,mode=0700",
            "--workdir", "/workspace", image, "python3", "-c", "import time;time.sleep(90)")
        execute("from pathlib import Path; p=Path('/workspace/project');p.mkdir();"
                "(p/'assets').mkdir();(p/'index.html').write_bytes(b'<h1>checkpoint</h1>');"
                "(p/'assets/data.bin').write_bytes(bytes(range(256)));"
                "(p/'.env').write_text('synthetic-excluded-value')")
        # All known writer commands have completed. Keep PID 1 alive during export.
        snapshot = execute(loader + "module.export_snapshot(Path('/workspace/project'),sys.stdout.buffer)").stdout
        with tempfile.TemporaryDirectory(prefix="atom-snapshot-probe-") as directory:
            verified = receive_snapshot(io.BytesIO(snapshot), Path(directory))
            assert (verified.path / "index.html").read_bytes() == b"<h1>checkpoint</h1>"
            assert (verified.path / "assets/data.bin").read_bytes() == bytes(range(256))
            assert not (verified.path / ".env").exists()
            report["live_export_verified"] = True
            report["revision"] = verified.revision
            run("docker", "stop", "--time", "1", name)
            assert run("docker", "inspect", name, "--format", "{{.State.Running}}").stdout.strip() == b"false"
            run("docker", "start", name)
            execute("from pathlib import Path;assert not Path('/workspace/project').exists()")
            report["stop_restart_loses_tmpfs"] = True
            execute(loader + "received=module.receive_snapshot(sys.stdin.buffer,Path('/workspace'));"
                    "received.path.rename('/workspace/project')", snapshot)
            restored = execute(loader + "module.export_snapshot(Path('/workspace/project'),sys.stdout.buffer)").stdout
            restored_verified = receive_snapshot(io.BytesIO(restored), Path(directory))
            assert restored == snapshot
            assert restored_verified.revision == verified.revision
            report["restore_exact_revision"] = True
            report["prior_host_snapshot_unchanged"] = (verified.path / "index.html").read_bytes() == b"<h1>checkpoint</h1>"
            assert report["prior_host_snapshot_unchanged"]
    finally:
        # Resolve uncertain create outcomes too; remove only this invocation's labelled container.
        ownership = run("docker", "inspect", name, "--format", '{{index .Config.Labels "atom.snapshot-probe"}}', check=False)
        if ownership.returncode == 0:
            if ownership.stdout.decode().strip() != owner:
                raise RuntimeError("probe ownership mismatch; container not removed")
            run("docker", "rm", "--force", name)
        remaining = run("docker", "ps", "-aq", "--filter", f"label=atom.snapshot-probe={owner}")
        if remaining.stdout.strip():
            raise RuntimeError("probe cleanup not confirmed")
        report["cleanup_confirmed"] = True
    print(json.dumps({"result": "PASS", **report}, sort_keys=True))


if __name__ == "__main__":
    main()
