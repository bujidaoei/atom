from __future__ import annotations

import time

import httpx

_CACHE_SECONDS = 60
_cache: dict[str, tuple[float, list[str]]] = {}

# Shown when the gateway cannot be reached, so the settings page still offers
# something selectable instead of an empty dropdown.
FALLBACK_MODELS = [
    "claude-sonnet-5",
    "gpt-5.6-sol",
    "deepseek-v4-pro",
    "qwen3.8-max",
    "glm-5.3",
]


async def list_models(base_url: str, api_key: str) -> list[str]:
    key = f"{base_url}|{api_key[-6:]}"
    cached = _cache.get(key)
    now = time.monotonic()
    if cached and now - cached[0] < _CACHE_SECONDS:
        return cached[1]

    models: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if response.status_code == 200:
                payload = response.json()
                models = [
                    str(item["id"])
                    for item in payload.get("data", [])
                    if isinstance(item, dict) and item.get("id")
                ]
    except (httpx.HTTPError, ValueError, KeyError):
        models = []

    # Image-only models cannot serve an agent turn; hide them from the picker.
    models = sorted(m for m in models if not _is_image_model(m))
    result = models or FALLBACK_MODELS
    _cache[key] = (now, result)
    return result


def _is_image_model(model: str) -> bool:
    lowered = model.lower()
    return any(token in lowered for token in ("image", "seedream", "banana", "qwen-image"))
