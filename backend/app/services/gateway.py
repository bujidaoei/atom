from __future__ import annotations

import time
import hashlib
import json

import httpx

_CACHE_SECONDS = 60
_cache: dict[str, tuple[float, list[str]]] = {}


async def list_models(base_url: str, api_key: str) -> list[str]:
    key = hashlib.sha256(json.dumps([base_url, api_key]).encode()).hexdigest()
    cached = _cache.get(key)
    now = time.monotonic()
    if cached and now - cached[0] < _CACHE_SECONDS:
        return cached[1]

    models: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            response = await client.get(
                f"{base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if response.status_code == 200:
                payload = response.json()
                data = payload.get("data") if isinstance(payload, dict) else None
                if isinstance(data, list):
                    models = [
                        item["id"] for item in data
                        if isinstance(item, dict)
                        and isinstance(item.get("id"), str)
                        and item["id"].strip()
                    ]
    except (httpx.HTTPError, ValueError, KeyError):
        models = []

    # Image-only models cannot serve an agent turn; hide them from the picker.
    models = sorted({m for m in models if not _is_image_model(m)})
    if models:
        # Discard expired entries and bound process memory across connections.
        for old in [k for k, (at, _) in _cache.items() if now - at >= _CACHE_SECONDS]:
            _cache.pop(old, None)
        if len(_cache) >= 256:
            _cache.pop(next(iter(_cache)))
        _cache[key] = (now, models)
    return models


def _is_image_model(model: str) -> bool:
    lowered = model.lower()
    return any(token in lowered for token in ("image", "seedream", "banana", "qwen-image"))
