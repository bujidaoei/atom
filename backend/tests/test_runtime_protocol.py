import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app.errors import RuntimeUnavailable
from app.services.runtime_client import GatewayConfig, RuntimeClient


@pytest.mark.parametrize(
    "body", ["", "invalid\n", '{"kind":"event","type":"run.completed"}\n']
)
def test_premature_eof_is_not_success(monkeypatch, body):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=body))
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs)
    )

    async def scenario():
        with pytest.raises(RuntimeUnavailable, match="未收到完成结果"):
            async for _ in RuntimeClient().run(
                run_id="r",
                role="alex",
                prompt="test",
                workspace_path=Path("."),
                session_path=Path("session"),
                agent_dir=Path("."),
                gateway=GatewayConfig("https://invalid", "test", "model"),
            ):
                pass

    asyncio.run(scenario())


def test_terminal_stops_reading_and_does_not_accept_a_second_result(monkeypatch):
    original = httpx.AsyncClient

    def response(request):
        assert json.loads(request.content)["budgetMs"] == 360000
        return httpx.Response(
            200,
            text='{"kind":"result","resultText":"first"}\n{"kind":"error","message":"late"}\n',
        )

    transport = httpx.MockTransport(response)
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs)
    )

    async def scenario():
        return [
            line
            async for line in RuntimeClient().run(
                run_id="r",
                budget_seconds=360,
                role="alex",
                prompt="test",
                workspace_path=Path("."),
                session_path=Path("session"),
                agent_dir=Path("."),
                gateway=GatewayConfig("https://invalid", "test", "model"),
            )
        ]

    lines = asyncio.run(scenario())
    assert len(lines) == 1 and lines[0].payload["resultText"] == "first"
