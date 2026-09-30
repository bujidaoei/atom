"""Trusted execution coordination across the API ledger and sandbox broker."""
import asyncio

from .revisions import Recovery, RevisionError, RevisionRepository
from .sandbox.client import BrokerClient, BrokerClientError


class ExecutionCoordinator:
    def __init__(self, repository: RevisionRepository, broker: BrokerClient):
        self.repository, self.broker = repository, broker

    async def _termination(self, owner: str, attempt_id: str, *, confirmed: bool) -> Recovery:
        try:
            await asyncio.to_thread(self.repository.observe_termination, owner, attempt_id,
                                    confirmed=confirmed, outcome='cancelled')
        except RevisionError as error:
            if error.code != 'revision_conflict':
                raise
            # A concurrent finalizer may already have recorded a different outcome.
            current = await asyncio.to_thread(self.repository.recovery, owner, attempt_id)
            if current.state != 'closed':
                raise
            return current
        return await asyncio.to_thread(self.repository.recovery, owner, attempt_id)

    async def cancel(self, owner: str, attempt_id: str) -> Recovery:
        """Durably fence dispatch before revocation; release only on broker proof."""
        intent = await asyncio.to_thread(self.repository.cancel, owner, attempt_id)
        if intent.state == 'closed':
            return intent
        try:
            await self.broker.revoke(intent.grant_id)
        except asyncio.CancelledError:
            await self._termination(owner, attempt_id, confirmed=False)
            raise
        except BrokerClientError:
            observed = await self._termination(owner, attempt_id, confirmed=False)
            if observed.state == 'closed':
                return observed
            raise
        return await self._termination(owner, attempt_id, confirmed=True)
