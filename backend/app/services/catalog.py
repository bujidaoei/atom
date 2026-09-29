import time

import httpx

FALLBACK_MODELS = [
    "glm-5.2",
    "qwen3-max",
    "qwen3.8-max",
    "qwen3.7-plus",
    "gpt-image-2.5",
    "deepseek-v4-pro",
    "deepseek-v4-flash",
    "dashscope/deepseek-v4-pro",
    "gpt-image-2",
]

_cache: dict[str, tuple[float, list[str]]] = {}


def list_model_ids(base_url: str, api_key: str) -> list[str]:
    base = (base_url or "").strip().rstrip("/")
    key = (api_key or "").strip()
    if not base.startswith("https://") or not key:
        return list(FALLBACK_MODELS)
    cache_key = f"{base}|{key[-4:]}"
    now = time.time()
    cached = _cache.get(cache_key)
    if cached and now - cached[0] < 60:
        return cached[1]
    try:
        response = httpx.get(
            f"{base}/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("data") if isinstance(payload, dict) else payload
        ids: list[str] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            model_id = str(row.get("id") or "").strip()
            if model_id and model_id not in ids:
                ids.append(model_id)
        if not ids:
            raise ValueError("empty catalog")
    except Exception:
        ids = list(FALLBACK_MODELS)
        _cache[cache_key] = (now - 45, ids)
        return ids
    _cache[cache_key] = (now, ids)
    return ids
