"""Locate the wall-clock ceiling on gateway responses.

Requests generations of increasing length, streaming and not, and reports
how long each survived. If a hard cutoff exists the failures cluster at one
duration regardless of model.
"""

from __future__ import annotations

import os
import time

import httpx

BASE = os.environ.get("ATOM_LLM_BASE_URL", "https://ai-gateway.skg.com/v1")
KEY = os.environ["ATOM_LLM_API_KEY"]
MODEL = os.environ.get("ATOM_LLM_MODEL", "claude-sonnet-5")

CASES = [
    ("stream", 800),
    ("stream", 2000),
    ("stream", 4000),
    ("plain", 2000),
    ("plain", 4000),
]

PROMPT_TEMPLATE = (
    "写一个完整的单文件 HTML 应用（习惯打卡，含内联 CSS 与 JS、"
    "localStorage 持久化）。只输出代码。目标长度约 {} token。"
)


def run(mode: str, max_tokens: int) -> None:
    started = time.monotonic()
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": PROMPT_TEMPLATE.format(max_tokens)}],
        "max_tokens": max_tokens,
        "stream": mode == "stream",
    }
    timeout = httpx.Timeout(connect=10, read=400, write=30, pool=10)
    try:
        if mode == "stream":
            chars = 0
            with httpx.stream(
                "POST",
                f"{BASE}/chat/completions",
                headers={"Authorization": f"Bearer {KEY}"},
                json=body,
                timeout=timeout,
            ) as response:
                for line in response.iter_lines():
                    chars += len(line)
            out = chars
        else:
            response = httpx.post(
                f"{BASE}/chat/completions",
                headers={"Authorization": f"Bearer {KEY}"},
                json=body,
                timeout=timeout,
            )
            out = len(response.text)
        print(f"{mode:<7} max={max_tokens:<5} OK   {time.monotonic() - started:6.1f}s  bytes={out}")
    except Exception as error:  # noqa: BLE001 - the failure mode is the result
        print(
            f"{mode:<7} max={max_tokens:<5} FAIL {time.monotonic() - started:6.1f}s  "
            f"{type(error).__name__}"
        )


print(f"model: {MODEL}  base: {BASE}")
for mode, tokens in CASES:
    run(mode, tokens)
