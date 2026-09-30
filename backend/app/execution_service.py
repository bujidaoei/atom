"""Application-owned execution resources, held under a Linux database lease."""
from contextlib import asynccontextmanager
from dataclasses import dataclass
import asyncio
import logging
import math
import os
import stat
import sys
import time
import uuid

from starlette.responses import JSONResponse

from .artifacts import ArtifactStore
from .execution import ExecutionCoordinator, ExecutionError
from .execution_http import ExecutionAPI
from .revisions import RevisionRepository, RevisionError
from .workspace_import import import_workspace
from .sandbox.client import BrokerClient
from .sandbox.grants import GrantCodec, CompletionGrantCodec


class DatabaseLease:
    """Cooperating API processes lock the same existing inode, never a new file."""
    def __init__(self, path):
        self.descriptor = None
        if sys.platform != 'linux':
            raise ExecutionError('unsupported_execution_platform')
        import fcntl
        try:
            self.descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            info = os.fstat(self.descriptor)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077):
                raise ExecutionError('unsafe_execution_database')
            fcntl.flock(self.descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, ExecutionError):
            self.close()
            raise ExecutionError('execution_database_unavailable') from None

    def close(self):
        if self.descriptor is not None:
            os.close(self.descriptor)
            self.descriptor = None


@dataclass(frozen=True)
class ExecutionResources:
    repository: RevisionRepository
    store: ArtifactStore
    coordinator: ExecutionCoordinator
    api: ExecutionAPI

    async def prepare_run(self, *, owner, project_id, run_id, heat_id, source, budget):
        if isinstance(budget, bool) or not isinstance(budget, (int, float)) or not 0 < budget <= 7140:
            raise ExecutionError('invalid_execution_budget')
        attempt, grant = uuid.uuid4().hex, uuid.uuid4().hex
        def reserve():
            workspace = self.repository.ensure_workspace(owner, project_id, heat_id)
            if self.repository.current_revision(owner, workspace) is None:
                import_workspace(self.repository, self.store, owner=owner, project_id=project_id,
                                 heat_id=heat_id, source=source)
            self.repository.reserve(owner, workspace, run_id, attempt, grant, int(time.time())+math.ceil(budget)+60)
        try:
            # Settle the finite local transaction before cancellation cleanup:
            # no background reservation may commit after cleanup observed absence.
            task = asyncio.create_task(asyncio.to_thread(reserve))
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                while not task.done():
                    try:
                        await asyncio.shield(task)
                    except asyncio.CancelledError:
                        continue
                    except Exception:
                        break
                if not task.cancelled():
                    task.exception()
                raise
            return await self.coordinator.prepare(owner, attempt, self.store)
        except BaseException as error:
            try:
                await asyncio.to_thread(self.repository.recovery, owner, attempt)
            except RevisionError as missing:
                if missing.code != 'revision_not_found':
                    raise
            else:
                try:
                    await self.coordinator.interrupt(owner, attempt,
                        'cancelled' if isinstance(error, asyncio.CancelledError) else 'failed')
                except Exception as cleanup:
                    logging.getLogger(__name__).error('execution_prepare_cleanup_failed',
                        extra={'exception_type':type(cleanup).__name__})
            raise


@asynccontextmanager
async def execution_resources(settings):
    if settings.sandbox_mode == 'local':
        yield None
        return
    lease = DatabaseLease(settings.db_path)
    try:
        repository = RevisionRepository(settings.db_path)
        store = ArtifactStore(settings.artifact_dir)
        completion = CompletionGrantCodec(settings.completion_grant_key.encode(), max_lifetime=7200)
        async with BrokerClient(settings.broker_origin, settings.broker_admin_token,
                                GrantCodec(settings.broker_grant_key.encode(), max_lifetime=7200)) as broker:
            await broker.require_ready()
            coordinator = ExecutionCoordinator(repository, broker, completion_codec=completion)
            await coordinator.reconcile()
            try:
                yield ExecutionResources(repository, store, coordinator, ExecutionAPI(coordinator, store, completion))
            finally:
                await coordinator.reconcile()
    finally:
        lease.close()


class ExecutionGateway:
    async def __call__(self, scope, receive, send):
        resources = getattr(scope['app'].state, 'execution', None)
        if resources is None:
            await JSONResponse({'error': 'execution_unavailable'}, status_code=503)(scope, receive, send)
            return
        await resources.api(scope, receive, send)
