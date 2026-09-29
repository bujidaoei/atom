import asyncio

from app.services.pi_runtime import pi_complete


async def complete(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    max_tokens: int,
    temperature: float | None = 0.2,
    on_event=None,
    extra: dict | None = None,
    timeout: int = 58,
) -> tuple[str, dict]:
    del temperature
    return await asyncio.to_thread(
        pi_complete,
        base_url=base_url,
        api_key=api_key,
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        on_event=on_event,
        extra=extra,
        timeout=timeout,
    )
