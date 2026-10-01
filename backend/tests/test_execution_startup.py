import asyncio

import pytest

from app.execution_service import _await_broker_ready
from app.sandbox.client import BrokerClientError


class ReadinessProbe:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.calls = 0

    async def require_ready(self):
        self.calls += 1
        outcome = next(self.outcomes)
        if outcome:
            raise BrokerClientError(outcome)


def test_api_waits_for_late_broker():
    probe = ReadinessProbe(['broker_outcome_unknown', 'broker_not_ready', None])
    asyncio.run(_await_broker_ready(probe, wait_seconds=1, retry_seconds=0.001))
    assert probe.calls == 3


def test_api_does_not_retry_authentication_failure():
    probe = ReadinessProbe(['broker_http_error'])
    with pytest.raises(BrokerClientError, match='broker_http_error'):
        asyncio.run(_await_broker_ready(probe, wait_seconds=1, retry_seconds=0.001))
    assert probe.calls == 1


def test_api_bounds_absent_broker():
    class AbsentBroker:
        async def require_ready(self):
            raise BrokerClientError('broker_outcome_unknown')

    with pytest.raises(BrokerClientError, match='broker_not_ready'):
        asyncio.run(_await_broker_ready(AbsentBroker(), wait_seconds=0.03, retry_seconds=0.01))
