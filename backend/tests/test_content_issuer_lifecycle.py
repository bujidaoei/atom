import asyncio

import pytest

from app.content_issuer_lifecycle import ContentIssuerLifecycle


def test_drain_retains_ownership_and_refuses_restart_until_completion():
    async def scenario():
        owner = ContentIssuerLifecycle(1)
        token = owner.acquire()
        assert token is not None and owner.acquire() is None
        with pytest.raises(RuntimeError, match='content_issuer_drain_timeout'):
            await owner.drain(.02)
        assert owner.pending_count == 1 and owner.acquire() is None
        with pytest.raises(RuntimeError, match='operations_pending'):
            owner.start()
        owner.release(token)
        await owner.drain(.02)
        assert owner.acquire() is None
        owner.start()
        replacement = owner.acquire()
        assert replacement is not None
        owner.release(replacement)
    asyncio.run(scenario())


def test_drain_waits_and_cancellation_does_not_reopen():
    async def scenario():
        owner = ContentIssuerLifecycle()
        token = owner.acquire()
        waiting = asyncio.create_task(owner.drain())
        await asyncio.sleep(.01)
        assert not waiting.done() and owner.acquire() is None
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        assert owner.pending_count == 1 and owner.acquire() is None
        owner.release(token)
        await owner.drain()
    asyncio.run(scenario())


@pytest.mark.parametrize('value', [0, -1, 61, float('nan'), float('inf'), True, '15'])
def test_invalid_deadlines_rejected(value):
    with pytest.raises(ValueError):
        asyncio.run(ContentIssuerLifecycle().drain(value))


def test_main_lifespan_reports_unfinished_issuer_shutdown(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services.orchestrator import orchestrator

    owner = ContentIssuerLifecycle()
    monkeypatch.setattr(app.state, 'content_issuer', owner)
    original = owner.drain

    async def short_drain():
        await original(.02)

    monkeypatch.setattr(owner, 'drain', short_drain)
    token = None
    try:
        with pytest.raises(RuntimeError, match='content_issuer_drain_timeout'):
            with TestClient(app):
                token = owner.acquire()
                assert token is not None
        assert owner.pending_count == 1 and owner.acquire() is None
        assert app.state.execution is None and orchestrator.execution is None
    finally:
        if token is not None:
            owner.release(token)
