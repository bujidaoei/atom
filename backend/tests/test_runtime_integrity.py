"""Guards on the vendored agent runtime.

The Pi tree is verified byte-for-byte at image build time. These tests catch
the cheaper failure first: files that never made it into the repository at
all, which is how a broad ignore rule silently breaks a deployment.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RUNTIME = REPO / "runtime"
LOCK = RUNTIME / "pi-source.lock.json"


def _lock() -> dict:
    return json.loads(LOCK.read_text("utf-8"))


def _tracked(prefix: str) -> set[str]:
    result = subprocess.run(
        ["git", "ls-files", prefix],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("git is unavailable")
    return {line for line in result.stdout.splitlines() if line}


def test_lock_file_is_present_and_pinned() -> None:
    lock = _lock()
    assert lock["version"] == "0.87.1"
    assert lock["upstreamCommit"]
    assert lock["fileCount"] > 1000


def test_every_locked_pi_file_is_committed() -> None:
    """A missing file here means the image build will refuse to start.

    Pi's own .gitignore excludes generated provider data, so those files have
    to be force-added; this test is what notices when they are not.
    """
    expected = _lock()["fileCount"]
    tracked = _tracked("runtime/pi")
    assert len(tracked) == expected, (
        f"仓库里只有 {len(tracked)} 个 Pi 文件，锁文件要求 {expected} 个。"
        " 多半是某条 .gitignore 规则匹配到了 runtime/pi 里的目录。"
    )


def test_provider_data_is_committed() -> None:
    """Offline runs read these; upstream treats them as build output."""
    data = _tracked("runtime/pi/packages/ai/src/providers/data")
    assert len(data) > 30
    assert any(path.endswith("/openai.json") for path in data)


def test_gateway_bundle_is_committed() -> None:
    bundle = _tracked("runtime/.cache")
    assert any(path.endswith("runtime.mjs") for path in bundle), (
        "预编译的网关 bundle 没进仓库，服务器上没法启动运行时。"
    )


def test_adapters_exist() -> None:
    for name in ("server.ts", "local-sandbox.ts", "squad.ts"):
        assert (RUNTIME / "src" / name).is_file()
