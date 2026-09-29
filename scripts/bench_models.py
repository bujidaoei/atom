"""Measure gateway latency per model so the planning tier can be chosen on data."""

from __future__ import annotations

import os
import time

import httpx

BASE = os.environ.get("ATOM_LLM_BASE_URL", "https://ai-gateway.skg.com/v1")
KEY = os.environ["ATOM_LLM_API_KEY"]

CANDIDATES = [
    "claude-sonnet-5",
    "claude-haiku-4-5",
    "gpt-5.6-sol",
    "gpt-5.6-luna",
    "deepseek-v4-pro",
    "deepseek-v4-flash",
    "deepseek-v4.1-flash",
    "qwen3.8-max",
    "qwen3.7-plus",
    "glm-5.3",
]

PROMPT = (
    "用一个 JSON 对象回答，不要有别的内容："
    '{"title":"...","summary":"...","kind":"tool","steps":[{"role":"iris","goal":"..."}],'
    '"clarification":null}。需求是：做一个每日习惯打卡工具。'
)

for model in CANDIDATES:
    started = time.monotonic()
    try:
        response = httpx.post(
            f"{BASE}/chat/completions",
            headers={"Authorization": f"Bearer {KEY}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": PROMPT}],
                "max_tokens": 700,
            },
            timeout=180.0,
        )
        elapsed = time.monotonic() - started
        if response.status_code != 200:
            print(f"{model:<24} HTTP {response.status_code}  {response.text[:90]}")
            continue
        body = response.json()
        usage = body.get("usage", {})
        text = body["choices"][0]["message"].get("content") or ""
        out = usage.get("completion_tokens") or 0
        rate = f"{out / elapsed:6.1f} tok/s" if elapsed and out else "        -"
        print(f"{model:<24} {elapsed:6.1f}s  out={out:<5} {rate}  {text[:40]!r}")
    except httpx.HTTPError as error:
        print(f"{model:<24} ERROR {error}")
