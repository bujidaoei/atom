"""Application-owned execution resources, held under a Linux database lease."""
from contextlib import asynccontextmanager
from dataclasses import dataclass
import os
import stat
import sys

from starlette.responses import JSONResponse

from .artifacts import ArtifactStore
from .execution import ExecutionCoordinator, ExecutionError
from .execution_http import ExecutionAPI
from .revisions import RevisionRepository
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


@asynccontextmanager
async def execution_resources(settings):
    if settings.sandbox_mode == 'local':
        yield None
        return
    lease = DatabaseLease(settings.db_path)
    try:
        repository = RevisionRepository(settings.db_path)
        store = ArtifactStore(settings.artifact_dir)
        completion = CompletionGrantCodec(settings.completion_grant_key.encode())
        async with BrokerClient(settings.broker_origin, settings.broker_admin_token,
                                GrantCodec(settings.broker_grant_key.encode())) as broker:
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
