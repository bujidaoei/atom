"""Owner-only console issuance for one exact, isolated revision preview."""
import asyncio
import re

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from ..bounded_operations import OwnedJSONResponse
from ..config import get_settings
from ..console_auth import credentials, request_session_token, require_auth_origin
from ..deps import OwnedProject
from ..preview_access import PreviewAccessError, PreviewAccessRepository
from ..preview_paths import view_root
from ..project_origins import ProjectOriginError, ProjectOriginRepository
from ..project_port_hosts import ProjectPortHosts
from .releases import _json_command


router = APIRouter(prefix='/projects', tags=['preview-access'])
_HEADERS = {'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'}
_REVISION = re.compile(r'[A-Za-z0-9_.-]{1,100}\Z')
_WORKERS = set()


def _deny(status):
    raise HTTPException(status, '无法打开该版本预览', headers=_HEADERS)


def _issue(settings, owner_id, source_id, project_id, revision_id, replace_view_id=None):
    origins = ProjectOriginRepository(settings.db_path,
        first_port=settings.ip_preview_first_port, last_port=settings.ip_preview_last_port)
    pair = origins.for_project(project_id)
    if pair is None:
        raise PreviewAccessError('preview_origin_required')
    hosts = ProjectPortHosts(settings.ip_preview_address, origins)
    grant = PreviewAccessRepository(settings.db_path).issue(
        owner_id=owner_id, source_session_id=source_id,
        project_id=project_id, revision_id=revision_id, replace_view_id=replace_view_id)
    return {'url': hosts.origin(pair.preview_port) + '/_atom/open#' + grant.secret,
            'expiresAt': grant.expires_at, 'revisionId': grant.revision_id,
            'viewId': grant.view_id, 'viewUrl': hosts.origin(pair.preview_port) + view_root(grant.view_id)}


def _finished(worker, lifecycle, admission):
    try:
        if not worker.cancelled():
            worker.exception()
    finally:
        lifecycle.release(admission)


@router.post('/{project_id}/preview-access')
async def open_revision_preview(project: OwnedProject, request: Request):
    settings = get_settings()
    if not settings.ip_preview_enabled:
        _deny(404)
    require_auth_origin(request)
    if request.headers.getlist('x-atom-intent') != ['open-revision-preview']:
        _deny(403)
    command = await _json_command(request)
    if (set(command) not in ({'revisionId'}, {'revisionId', 'replaceViewId'})
            or type(command.get('revisionId')) is not str
            or _REVISION.fullmatch(command['revisionId']) is None):
        _deny(400)
    if 'replaceViewId' in command and (type(command['replaceViewId']) is not str
            or re.fullmatch(r'[0-9a-f]{64}', command['replaceViewId']) is None):
        _deny(400)
    token = request_session_token(request)
    source = credentials().authenticate(token) if token else None
    if source is None or source.user_id != project.user_id:
        _deny(401)
    lifecycle = request.app.state.content_issuer
    admission = lifecycle.acquire()
    if admission is None:
        _deny(503)
    release = True
    try:
        worker = asyncio.create_task(run_in_threadpool(_issue, settings, source.user_id,
            source.id, project.id, command['revisionId'], command.get('replaceViewId')))
        _WORKERS.add(worker)
        worker.add_done_callback(_WORKERS.discard)
        try:
            result = await asyncio.shield(worker)
        except asyncio.CancelledError:
            release = False
            worker.add_done_callback(lambda done: _finished(done, lifecycle, admission))
            raise
        response = OwnedJSONResponse(result, lifecycle, admission, headers=_HEADERS)
        release = False
        return response
    except PreviewAccessError as error:
        _deny(429 if str(error) == 'preview_capacity' else
              404 if str(error) in ('preview_access_denied', 'preview_origin_required') else 503)
    except ProjectOriginError:
        _deny(503)
    finally:
        if release:
            lifecycle.release(admission)
