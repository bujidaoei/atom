import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.errors import RuntimeUnavailable
from app.execution import ExecutionLease
from app.services.runtime_client import GatewayConfig, RuntimeClient


def test_broker_api_refuses_unleased_dispatch(monkeypatch, tmp_path):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), 'sandbox_mode', 'broker')
    async def scenario():
        with pytest.raises(RuntimeUnavailable, match='已准备的执行租约'):
            async for _ in RuntimeClient().run(run_id='r',role='alex',prompt='test',
                    workspace_path=tmp_path,session_path=tmp_path/'session',agent_dir=tmp_path,
                    gateway=GatewayConfig('https://invalid','synthetic','model')):
                raise AssertionError('unleased dispatch yielded output')
    asyncio.run(scenario())


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


def test_broker_premature_eof_does_not_claim_uncommitted_files(monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), 'sandbox_mode', 'broker')
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=''))
    monkeypatch.setattr(httpx, 'AsyncClient',
                        lambda **kwargs: original(transport=transport, **kwargs))
    lease = ExecutionLease('run', 'workspace', 'a' * 32, 4102444800,
                           'execution', 'grant-id', 'grant-token', 'completion-token')

    class Repository:
        def execution(self, owner, attempt_id):
            assert owner == 'owner' and attempt_id == lease.execution_id
            return SimpleNamespace(run_id=lease.run_id, workspace_id=lease.workspace_id,
                broker_attempt_id=lease.attempt_id, grant_id=lease.grant_id,
                deadline=lease.deadline)

    async def scenario():
        with pytest.raises(RuntimeUnavailable, match='未完成的文件未保存'):
            async for _ in RuntimeClient().run(run_id='run', role='alex', prompt='test',
                    workspace_path=Path('.'), session_path=Path('session'), agent_dir=Path('.'),
                    gateway=GatewayConfig('https://invalid', 'test', 'model'),
                    execution_lease=lease, execution_repository=Repository(),
                    execution_owner='owner'):
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
