"""Concurrent race admission must wait without losing bounded ownership."""
import asyncio

import pytest

from app.execution import ExecutionCoordinator, ExecutionError


def coordinator():
    value = object.__new__(ExecutionCoordinator)
    value._coordination = asyncio.Lock()
    value._admission_waiters = 0
    return value


def test_four_overlapping_heats_wait_for_serialized_setup():
    async def scenario():
        owner = coordinator()
        order = []

        async def heat(index):
            async with owner._admission():
                order.append(index)
                await asyncio.sleep(1.05)

        await asyncio.gather(*(heat(index) for index in range(4)))
        assert order == [0, 1, 2, 3]
        assert owner._admission_waiters == 0
        assert not owner._coordination.locked()

    asyncio.run(scenario())


def test_overflow_and_cancelled_waiter_never_take_lock():
    async def scenario():
        owner = coordinator()
        async with owner._admission():
            entered = []

            async def wait(index):
                async with owner._admission():
                    entered.append(index)

            queued = [asyncio.create_task(wait(index)) for index in range(8)]
            await asyncio.sleep(0)
            assert owner._admission_waiters == 8
            with pytest.raises(ExecutionError, match='execution_busy'):
                async with owner._admission():
                    pytest.fail('overflow entered')
            queued[3].cancel()
            with pytest.raises(asyncio.CancelledError):
                await queued[3]
            assert owner._admission_waiters == 7
            replacement = asyncio.create_task(wait(8))
            await asyncio.sleep(0)
            assert owner._admission_waiters == 8
        await asyncio.gather(*(task for task in queued if not task.cancelled()), replacement)
        assert entered == [0, 1, 2, 4, 5, 6, 7, 8]
        assert owner._admission_waiters == 0
        assert not owner._coordination.locked()

    asyncio.run(scenario())
