"""Check whether the gateway can hold a long streaming generation open.

The agent runtime reported connections dropping a few dozen tokens in. This
asks each candidate build model for a large file in one response and reports
where the stream stopped.
"""

from __future__ import annotations

import os
import sys
import time

import httpx

BASE = os.environ.get("ATOM_LLM_BASE_URL", "https://ai-gateway.skg.com/v1")
KEY = os.environ["ATOM_LLM_API_KEY"]
MODELS = sys.argv[1:] or ["claude-sonnet-5", "gpt-5.6-luna", "deepseek-v4-pro", "glm-5.3"]

PROMPT = (
    "输出一个完整的单文件 HTML 习惯打卡应用，要求包含内联 CSS 和 JS，"
    "支持添加习惯、勾选完成、localStorage 持久化、连续天数统计。"
    "只输出代码，不要解释。代码要完整，不少于 200 行。"
)


def probe(model: str) -> None:
    started = time.monotonic()
    chunks = 0
    chars = 0
    finish_reason = None
    try:
        with httpx.stream(
            "POST",
            f"{BASE}/chat/completions",
            headers={"Authorization": f"Bearer {KEY}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": PROMPT}],
                "max_tokens": 8000,
                "stream": True,
            },
            timeout=httpx.Timeout(connect=10, read=300, write=30, pool=10),
        ) as response:
            if response.status_code != 200:
                print(f"{model:<20} HTTP {response.status_code} {response.read()[:120]!r}")
                return
            for line in response.iter_lines():
                if not line.startswith("data: "):
                    continue
                if line.strip() == "data: [DONE]":
                    break
                chunks += 1
                chars += len(line)
                if '"finish_reason":"' in line:
                    finish_reason = line.split('"finish_reason":"')[1].split('"')[0]
        elapsed = time.monotonic() - started
        print(
            f"{model:<20} OK   {elapsed:6.1f}s  chunks={chunks:<5} chars={chars:<7} "
            f"finish={finish_reason}"
        )
    except Exception as error:  # noqa: BLE001 - the failure mode is the result
        elapsed = time.monotonic() - started
        print(
            f"{model:<20} FAIL {elapsed:6.1f}s  chunks={chunks:<5} chars={chars:<7} "
            f"{type(error).__name__}: {error}"
        )


for name in MODELS:
    probe(name)
