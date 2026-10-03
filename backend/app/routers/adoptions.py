"""Owner-authorized, revision-bound adoption of a completed race heat."""
import asyncio
import re

from fastapi import APIRouter, HTTPException, Request

from ..adoption_repository import AdoptionError, AdoptionRepository
from ..bounded_operations import OwnedJSONResponse
from ..config import get_settings
from ..console_auth import require_auth_origin
from ..deps import OwnedProject
from .releases import _json_command


router = APIRouter(prefix='/projects', tags=['adoptions'])
_HEADERS = {'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'}
_ID = re.compile(r'[A-Za-z0-9_-]{1,128}\Z')
_WORKERS = set()


def _deny(status: int, detail: str):
    raise HTTPException(status, detail, headers=_HEADERS)


def _finished(worker, lifecycle, token):
    try:
        if not worker.cancelled():
            worker.exception()
    finally:
        lifecycle.release(token)


@router.post('/{project_id}/race/{heat_id}/adopt')
async def adopt_heat(project: OwnedProject, heat_id: str, request: Request):
    require_auth_origin(request)
    if request.headers.getlist('x-atom-intent') != ['adopt-heat-revision']:
        _deny(403, '请选择要采用的已保存版本')
    settings = get_settings()
    if settings.sandbox_mode != 'broker' or settings.session_mode != 'durable':
        _deny(404, '版本采用暂不可用')
    if _ID.fullmatch(heat_id) is None:
        _deny(400, '赛道编号无效')
    command = await _json_command(request, '采用')
    if (set(command) != {'commandId', 'sourceRevisionId', 'expectedMainRevisionId'}
            or any(type(command[key]) is not str or _ID.fullmatch(command[key]) is None
                   for key in ('commandId', 'sourceRevisionId'))
            or (command['expectedMainRevisionId'] is not None and
                (type(command['expectedMainRevisionId']) is not str or
                 _ID.fullmatch(command['expectedMainRevisionId']) is None))):
        _deny(400, '采用请求格式不正确')
    resources = getattr(request.app.state, 'execution', None)
    if resources is None:
        _deny(503, '版本服务暂不可用')
    lifecycle = request.app.state.release_operations
    token = lifecycle.acquire()
    if token is None:
        _deny(503, '版本服务繁忙，请稍后重试')
    release = True
    try:
        def apply():
            receipt = AdoptionRepository(settings.db_path).adopt(
                owner=project.user_id, project_id=project.id, heat_id=heat_id,
                source_revision_id=command['sourceRevisionId'],
                expected_main_revision_id=command['expectedMainRevisionId'],
                command_id=command['commandId'], store=resources.store)
            return {'commandId': receipt.command_id,
                    'sourceRevisionId': receipt.source_revision_id,
                    'revisionId': receipt.revision_id}

        worker = asyncio.create_task(asyncio.to_thread(apply))
        _WORKERS.add(worker)
        worker.add_done_callback(_WORKERS.discard)
        try:
            result = await asyncio.shield(worker)
        except asyncio.CancelledError:
            release = False
            worker.add_done_callback(lambda done: _finished(done, lifecycle, token))
            raise
        response = OwnedJSONResponse(result, lifecycle, token, headers=_HEADERS)
        release = False
        return response
    except AdoptionError as error:
        if error.code == 'adoption_not_found':
            status, detail = 404, '该赛道不存在'
        elif error.code == 'adoption_conflict':
            status, detail = 409, '版本已经变化，请刷新后重新选择'
        elif error.code in ('adoption_artifact_unavailable', 'adoption_artifact_mismatch'):
            status, detail = 503, '已保存版本暂时无法读取，未改变主工作区'
        else:
            status, detail = 503, '版本采用暂时无法完成，请稍后重试'
        response = OwnedJSONResponse({'detail': detail}, lifecycle, token,
                                     status_code=status, headers=_HEADERS)
        release = False
        return response
    finally:
        if release:
            lifecycle.release(token)
