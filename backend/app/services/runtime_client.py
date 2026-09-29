from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from ..config import get_settings
from ..errors import RuntimeUnavailable


@dataclass(frozen=True)
class GatewayConfig:
    base_url: str
    api_key: str
    model: str


@dataclass(frozen=True)
class RuntimeLine:
    """One NDJSON line from the sidecar.

    ``kind`` is ``event`` for a pass-through runtime event, ``result`` for the
    successful terminal line, and ``error`` for the failed one.
    """

    kind: str
    type: str | None
    payload: dict[str, Any]

    @property
    def is_terminal(self) -> bool:
        return self.kind in {"result", "error"}


class RuntimeClient:
    """Thin HTTP client for the Node agent runtime sidecar."""

    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = settings.runtime_url.rstrip("/")
        self._headers = (
            {"Authorization": f"Bearer {settings.runtime_token}"}
            if settings.runtime_token
            else {}
        )
        # `read` bounds the gap between NDJSON lines, not the whole turn, but
        # a tool call can run silently for a while, so it tracks the run
        # budget rather than the single-model-call budget.
        self._timeout = httpx.Timeout(
            connect=10.0, read=settings.run_timeout_seconds, write=30.0, pool=10.0
        )

    async def healthy(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self._base_url}/healthz")
                return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def run(
        self,
        *,
        run_id: str,
        role: str,
        prompt: str,
        workspace_path: Path,
        session_path: Path,
        agent_dir: Path,
        gateway: GatewayConfig,
        context: str | None = None,
        enable_tools: bool | None = None,
    ) -> AsyncIterator[RuntimeLine]:
        """Stream one agent turn. Yields every line until a terminal one."""
        body: dict[str, Any] = {
            "runId": run_id,
            "role": role,
            "prompt": prompt,
            "workspacePath": str(workspace_path),
            "sessionPath": str(session_path),
            "agentDir": str(agent_dir),
            "gateway": {
                "baseUrl": gateway.base_url,
                "apiKey": gateway.api_key,
                "model": gateway.model,
                "requestTimeoutMs": get_settings().llm_timeout_seconds * 1000,
            },
        }
        if context:
            body["systemPromptSuffix"] = context
        if enable_tools is not None:
            body["enableTools"] = enable_tools

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                async with client.stream(
                    "POST", f"{self._base_url}/v1/runs", json=body, headers=self._headers
                ) as response:
                    if response.status_code != 200:
                        detail = (await response.aread()).decode("utf-8", "replace")[:400]
                        raise RuntimeUnavailable(
                            f"运行时返回 {response.status_code}：{detail}"
                        )
                    async for line in response.aiter_lines():
                        parsed = _parse_line(line)
                        if parsed is not None:
                            yield parsed
        except httpx.HTTPError as error:
            raise RuntimeUnavailable(f"agent 运行时连接中断：{_describe(error)}") from error

    async def cancel(self, run_id: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    f"{self._base_url}/v1/runs/{run_id}/cancel", headers=self._headers
                )
        except httpx.HTTPError:
            # Cancellation is advisory; the orchestrator also drops its own
            # task, and an unreachable sidecar has nothing left to cancel.
            pass


def _describe(error: Exception) -> str:
    """httpx timeout exceptions stringify to an empty message, which makes the
    UI show a blank failure. Always fall back to the class name."""
    return str(error) or type(error).__name__


def _parse_line(line: str) -> RuntimeLine | None:
    line = line.strip()
    if not line:
        return None
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    kind = str(data.get("kind", ""))
    if kind == "event":
        return RuntimeLine(
            kind="event",
            type=str(data.get("type", "")),
            payload=data.get("payload") if isinstance(data.get("payload"), dict) else {},
        )
    if kind in {"result", "error"}:
        return RuntimeLine(kind=kind, type=None, payload=data)
    return None


runtime_client = RuntimeClient()
