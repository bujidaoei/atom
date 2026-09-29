import json
import os
import shutil
import subprocess
import threading
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
    on_event=None,
    extra: dict | None = None,
    timeout: int = 58,
) -> tuple[str, dict]:
    node = os.environ.get("ATOM_PI_NODE") or shutil.which("node")
    entry = os.environ.get("ATOM_PI_ENTRY") or str(_ENTRY)
    if not node:
        raise GatewayError("服务器上没有 Node.js，Pi agent 无法启动。")
    if not Path(entry).is_file():
        raise GatewayError("找不到 Pi agent 运行时。")
    env = os.environ.copy()
    env["PI_OFFLINE"] = "1"
    payload = {
        "baseUrl": base_url,
        "apiKey": api_key,
        "model": model,
        "maxTokens": max_tokens,
        "messages": messages,
    }
    if extra:
        payload.update(extra)
    try:
        process = subprocess.Popen(
            [node, entry],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=env,
        )
    except OSError as exc:
        raise GatewayError("Pi agent 没有启动。") from exc
    final: dict | None = None
    stderr_lines: list[str] = []
    stopped = {"late": False}

    def stop() -> None:
        stopped["late"] = True
        process.kill()

    killer = threading.Timer(timeout, stop)
    killer.start()
    try:
        assert process.stdin is not None and process.stdout is not None and process.stderr is not None
        process.stdin.write(json.dumps(payload, ensure_ascii=False))
        process.stdin.close()
        while True:
            line = process.stdout.readline()
            if line == "":
                break
            raw = line.strip()
            if not raw:
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("event") == "done" or ("text" in event and "event" not in event):
                final = event
            elif on_event is not None:
                on_event(event)
        stderr_lines = [line.strip() for line in process.stderr.read().splitlines() if line.strip()]
        code = process.wait(timeout=5)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        raise GatewayError("模型网关超时，Pi agent 已停止这一轮。") from exc
    finally:
        killer.cancel()
    if stopped["late"] and final is None:
        raise GatewayError("模型网关超时，Pi agent 已停止这一轮。")
    if code != 0 or final is None:
        message = stderr_lines[-1] if stderr_lines else "Pi agent 没有完成这一轮。"
        lowered = message.lower()
        if "timed out" in lowered or "timeout" in lowered:
            message = "模型网关没有连上。请再试一次；如果还是不行，换 qwen3.7-plus。"
        raise GatewayError(message[:300])
    text = str(final.get("text") or "").strip()
    html = str(final.get("html") or "").strip()
    if not text and not html:
        raise GatewayError("Pi agent 返回了空内容。")
    return text, {
        "model": str(final.get("model") or model),
        "prompt_tokens": int(final.get("prompt_tokens") or 0),
        "completion_tokens": int(final.get("completion_tokens") or 0),
        "html": html,
        "notes": str(final.get("notes") or ""),
        "trace": str(final.get("trace") or ""),
        "checks": str(final.get("checks") or ""),
    }
