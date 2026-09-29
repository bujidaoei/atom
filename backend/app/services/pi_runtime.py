import json
import os
import shutil
import subprocess
from pathlib import Path

from app.errors import GatewayError

_ENTRY = Path(__file__).resolve().parents[3] / "runtime" / "run.mjs"


def pi_complete(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    max_tokens: int,
) -> tuple[str, dict]:
    node = os.environ.get("ATOM_PI_NODE") or shutil.which("node")
    entry = os.environ.get("ATOM_PI_ENTRY") or str(_ENTRY)
    if not node:
        raise GatewayError("服务器上没有 Node.js，Pi agent 无法启动。")
    if not Path(entry).is_file():
        raise GatewayError("找不到 Pi agent 运行时。")
    env = os.environ.copy()
    env["PI_OFFLINE"] = "1"
    try:
        completed = subprocess.run(
            [node, entry],
            input=json.dumps(
                {
                    "baseUrl": base_url,
                    "apiKey": api_key,
                    "model": model,
                    "maxTokens": max_tokens,
                    "messages": messages,
                },
                ensure_ascii=False,
            ),
            capture_output=True,
            text=True,
            timeout=58,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise GatewayError("模型网关超时，Pi agent 已停止这一轮。") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        message = detail[-1] if detail else "Pi agent 没有完成这一轮。"
        if "timed out" in message.lower() or "timeout" in message.lower():
            message = "模型网关没有连上。请再试一次；如果还是不行，换 qwen3.7-plus。"
        raise GatewayError(message[:300])
    raw = completed.stdout.strip()
    line = raw[raw.rfind("\n") + 1 :] if raw else ""
    try:
        body = json.loads(line)
    except json.JSONDecodeError as exc:
        raise GatewayError("Pi agent 没有返回可解析的结果。") from exc
    text = str(body.get("text") or "").strip()
    if not text:
        raise GatewayError("Pi agent 返回了空内容。")
    return text, {
        "model": str(body.get("model") or model),
        "prompt_tokens": int(body.get("prompt_tokens") or 0),
        "completion_tokens": int(body.get("completion_tokens") or 0),
    }
