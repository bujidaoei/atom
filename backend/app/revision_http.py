"""Bounded synchronous route access to committed project files."""
from contextlib import contextmanager
from threading import BoundedSemaphore

from fastapi import HTTPException

from .artifacts import ArtifactError
from .revisions import RevisionError
from .revision_view import materialized_revision, committed_catalog
from .snapshots import SnapshotError

_READS = BoundedSemaphore(1)


@contextmanager
def _resources(request):
    resources = getattr(request.app.state, 'execution', None)
    if resources is None:
        raise HTTPException(503, '版本服务暂不可用')
    if not _READS.acquire(timeout=3):
        raise HTTPException(503, '版本读取繁忙，请重试')
    try:
        yield resources
    except RevisionError as error:
        if error.code in ('revision_not_found', 'revision_not_initialized', 'invalid_revision_request'):
            raise HTTPException(404, '还没有已登记的文件版本') from None
        raise HTTPException(503, '版本暂不可读取') from None
    except (ArtifactError, SnapshotError, OSError):
        raise HTTPException(503, '版本暂不可读取') from None
    finally:
        _READS.release()


@contextmanager
def project_revision_view(request, project, heat_id=None):
    with _resources(request) as resources:
        workspace = resources.repository.find_workspace(project.user_id, project.id, heat_id)
        with materialized_revision(resources.repository, resources.store,
                                   owner=project.user_id, workspace_id=workspace) as view:
            yield view


def project_catalog(request, project):
    """OwnedProject routes supply the authenticated project; no rows are created."""
    def read(heat_id=None):
        with _resources(request) as resources:
            return committed_catalog(resources.repository, resources.store, owner=project.user_id,
                                     project_id=project.id, heat_id=heat_id)
    return read
