"""Trusted execution coordination across the API ledger and sandbox broker."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import io

from .artifacts import ArtifactStore, ArtifactError
from .revisions import Recovery, RevisionError, RevisionRepository
from .sandbox.client import BrokerClient, BrokerClientError
from .sandbox.grants import Grant
from .snapshots import verify_snapshot, SnapshotError


class ExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExecutionLease:
    run_id: str
    workspace_id: str
    attempt_id: str
    deadline: int
    grant: str = field(repr=False)


class ExecutionCoordinator:
    def __init__(self, repository: RevisionRepository, broker: BrokerClient):
        self.repository, self.broker = repository, broker
        self._coordination = asyncio.Lock()

    async def _termination(self, owner: str, attempt_id: str, *, confirmed: bool,
                           outcome: str = 'cancelled') -> Recovery:
        try:
            await asyncio.to_thread(self.repository.observe_termination, owner, attempt_id,
                                    confirmed=confirmed, outcome=outcome)
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
        return await self._stop(owner, attempt_id, 'cancelled')

    async def _stop(self, owner: str, attempt_id: str, outcome: str) -> Recovery:
        if outcome == 'succeeded':
            intent = await asyncio.to_thread(self.repository.recovery, owner, attempt_id)
            if intent.state != 'active' and intent.state != 'closed':
                return await self._stop(owner, attempt_id, 'cancelled')
        else:
            intent = await asyncio.to_thread(self.repository.cancel, owner, attempt_id)
        if intent.state == 'closed':
            return intent
        try:
            await self.broker.revoke(intent.grant_id)
        except asyncio.CancelledError:
            await self._termination(owner, attempt_id, confirmed=False, outcome=outcome)
            raise
        except BrokerClientError:
            observed = await self._termination(owner, attempt_id, confirmed=False, outcome=outcome)
            if observed.state == 'closed':
                return observed
            raise
        return await self._termination(owner, attempt_id, confirmed=True, outcome=outcome)

    @staticmethod
    def _base(store: ArtifactStore, key: str, revision: str) -> bytes:
        payload = store.read(key)
        if verify_snapshot(io.BytesIO(payload)).revision != revision:
            raise ExecutionError('execution_base_mismatch')
        return payload

    @asynccontextmanager
    async def _admission(self):
        try:
            async with asyncio.timeout(3):
                await self._coordination.acquire()
        except TimeoutError:
            raise ExecutionError('execution_busy') from None
        try:
            yield
        finally:
            self._coordination.release()

    async def prepare(self, owner: str, attempt_id: str, store: ArtifactStore) -> ExecutionLease:
        """Prepare an existing durable reservation; never infer one from runtime."""
        async with self._admission():
            intent = await asyncio.to_thread(self.repository.execution, owner, attempt_id)
            try:
                payload = await asyncio.to_thread(self._base, store, intent.base_artifact_key, intent.base_revision)
                grant = Grant(intent.grant_id, owner, intent.project_id, intent.run_id, intent.id,
                              intent.generation, intent.base_revision, intent.issued_at, intent.deadline)
                token = self.broker.runtime_token(grant)
                await asyncio.to_thread(self.repository.execution, owner, attempt_id)
                observed = await self.broker.provision(grant)
                bound = await asyncio.to_thread(self.repository.bind, owner, attempt_id, observed.attempt_id)
                if observed.state == 'provisioning':
                    await self.broker.seed(grant, observed.attempt_id, payload)
                current = await asyncio.to_thread(self.repository.execution, owner, attempt_id)
                if current != bound:
                    raise ExecutionError('execution_changed')
                return ExecutionLease(current.run_id, current.workspace_id, observed.attempt_id,
                                      current.deadline, token)
            except asyncio.CancelledError:
                await self._stop(owner, attempt_id, 'cancelled')
                raise
            except (ArtifactError, SnapshotError, RevisionError, BrokerClientError, ExecutionError):
                await self._stop(owner, attempt_id, 'failed')
                raise

    async def complete(self, owner: str, attempt_id: str, store: ArtifactStore) -> Recovery:
        """Register verified output before checkpoint acknowledgement and release."""
        async with self._admission():
            previous = await asyncio.to_thread(self.repository.recovery, owner, attempt_id)
            if previous.state == 'closed':
                return previous
            try:
                intent = await asyncio.to_thread(self.repository.completion, owner, attempt_id)
                grant = Grant(intent.grant_id, owner, intent.project_id, intent.run_id, intent.id,
                              intent.generation, intent.base_revision, intent.issued_at, intent.deadline)
                receipt = await asyncio.to_thread(self.repository.receipt, owner, attempt_id,
                                                 intent.broker_attempt_id, intent.grant_id)
                acknowledged = False
                if receipt is not None:
                    status = await self.broker.checkpoint_status(grant, intent.broker_attempt_id)
                    if status.state == 'checkpointed':
                        if status.revision != receipt.snapshot_revision:
                            raise ExecutionError('execution_checkpoint_mismatch')
                        # Recovery must still establish that the registered bytes exist.
                        await asyncio.to_thread(self._base, store, receipt.artifact_key, receipt.snapshot_revision)
                        acknowledged = True
                if not acknowledged:
                    exported = await self.broker.export(grant, intent.broker_attempt_id)
                    artifact = await asyncio.to_thread(store.put, exported.payload)
                    receipt = await asyncio.to_thread(self.repository.register, owner, attempt_id,
                                                     intent.broker_attempt_id, intent.grant_id, artifact)
                    await asyncio.to_thread(self.repository.completion, owner, attempt_id)
                    await self.broker.confirm(grant, exported, receipt)
                await asyncio.to_thread(self.repository.completion, owner, attempt_id)
                return await self._stop(owner, attempt_id, 'succeeded')
            except asyncio.CancelledError:
                await self._stop(owner, attempt_id, 'cancelled')
                raise
            except (ArtifactError, SnapshotError, RevisionError, BrokerClientError, ExecutionError):
                await self._stop(owner, attempt_id, 'failed')
                raise
