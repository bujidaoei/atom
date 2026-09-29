import asyncio
import logging

import httpx

from app.errors import GatewayError

logger = logging.getLogger(__name__)


def _message_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts)
    return ""


async def complete(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    max_tokens: int,
    temperature: float | None = 0.2,
) -> tuple[str, dict]:
    if not api_key:
        raise GatewayError("还没有可用的 API Key。请到设置里填写，或由部署方配置服务器默认密钥。")
    url = base_url.rstrip("/") + "/chat/completions"
    payload: dict = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        # This gateway buffers the whole reply and drops the connection around 60 seconds.
        # Turning thinking off keeps Qwen inside that window.
        "enable_thinking": False,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            return await _post(url, headers, payload, model)
        except GatewayError as exc:
            if attempt == 0 and "400" in str(exc):
                payload.pop("enable_thinking", None)
                payload.pop("temperature", None)
                continue
            raise
        except httpx.HTTPError as exc:
            last_error = exc
            logger.warning("gateway transport error on attempt %s: %s", attempt + 1, type(exc).__name__)
            if attempt == 0:
                await asyncio.sleep(1)
    raise GatewayError("连不上模型网关，请检查地址或稍后再试。") from last_error


async def _post(url: str, headers: dict, payload: dict, model: str) -> tuple[str, dict]:
    timeout = httpx.Timeout(58.0, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=payload, headers=headers)
    if response.status_code >= 400:
        logger.warning("gateway status %s", response.status_code)
        detail = response.text[:180].replace("\n", " ")
        raise GatewayError(f"模型网关返回 {response.status_code}。{detail}")
    try:
        body = response.json()
    except ValueError as exc:
        raise GatewayError("模型网关没有返回 JSON。") from exc
    choices = body.get("choices") or []
    if not choices:
        raise GatewayError("模型没有返回内容。")
    text = _message_text(choices[0].get("message", {}).get("content"))
    if not text.strip():
        raise GatewayError("模型返回是空的。")
    usage = body.get("usage") or {}
    return text, {
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "model": str(body.get("model") or model),
    }
