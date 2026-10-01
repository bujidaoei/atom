"""Authenticated v13 verification control plane; release remains a separate gate."""
from __future__ import annotations

import asyncio
import json
import re
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.requests import ClientDisconnect

from ..config import get_settings
from ..console_auth import require_auth_origin, require_console_host
from ..deps import OwnedProject
from ..verification_repository import (VerificationError, VerificationRepository,
                                       VerificationState)
from ..verifier_client import VerifierClientError


router = APIRouter(prefix='/projects', tags=['verifications'])
_HEADERS = {'Cache-Control':'no-store'}
_REQUEST_ID = re.compile(r'[0-9a-f]{32}\Z')


def _deny(status: int, message: str):
    raise HTTPException(status, message, headers=_HEADERS)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_key')
        result[key] = value
    return result


async def _request_id(request: Request):
    headers = request.scope['headers']
    lengths = [value for key, value in headers if key.lower() == b'content-length']
    if (request.scope.get('query_string')
            or [value.lower() for key, value in headers if key.lower() == b'content-type']
               != [b'application/json']
            or len(lengths) != 1 or re.fullmatch(rb'[0-9]{1,3}', lengths[0]) is None
            or not 1 <= int(lengths[0]) <= 128
            or any(key.lower() in (b'content-encoding',b'transfer-encoding')
                   for key, _ in headers)):
        _deny(400, '验证请求格式不正确')
    body = bytearray()
    try:
        async with asyncio.timeout(5):
            async for chunk in request.stream():
                if len(body) + len(chunk) > 128:
                    _deny(413, '验证请求过大')
                body.extend(chunk)
    except (TimeoutError, ClientDisconnect):
        _deny(400, '验证请求未完整送达')
    if len(body) != int(lengths[0]):
        _deny(400, '验证请求未完整送达')
    try:
        value = json.loads(body.decode('utf-8'), object_pairs_hook=_unique,
                           parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, RecursionError):
        _deny(400, '验证请求格式不正确')
    if (type(value) is not dict or set(value) != {'requestId'}
            or type(value['requestId']) is not str
            or _REQUEST_ID.fullmatch(value['requestId']) is None):
        _deny(400, '验证请求格式不正确')
    return value['requestId']


def _configured(request: Request):
    settings = get_settings()
    if (settings.sandbox_mode != 'broker' or settings.session_mode != 'durable'
            or settings.verifier_origin is None):
        _deny(404, '验证服务尚未启用')
    client = getattr(request.app.state, 'verifier_client', None)
    if client is None:
        _deny(503, '验证服务暂不可用')
    return settings, client


def _repository_error(error: VerificationError):
    code = str(error)
    if code == 'verification_not_found':
        _deny(404, '验证请求不存在')
    if code in ('verification_conflict', 'verification_expired',
                'invalid_stored_contract'):
        _deny(409, '当前版本或需求已变化，请刷新后重试')
    _deny(503, '验证账本暂不可用')


def _view(state: VerificationState):
    request = state.request
    result = state.result
    if result is not None:
        name = result.outcome
    elif request.deadline <= time.time():
        name = 'unresolved' if state.dispatched else 'expired'
    else:
        name = 'running' if state.dispatched else 'reserved'
    return {'requestId':request.id, 'revisionId':request.revision_id,
            'contractDigest':request.contract.digest, 'state':name,
            'deadline':request.deadline, 'total':result.total if result else None,
            'passed':result.passed if result else None,
            'completedAt':result.completed_at if result else None}


async def _describe(repository, owner, project_id, request_id):
    try:
        return await asyncio.to_thread(repository.describe, owner=owner,
                                       project_id=project_id, request_id=request_id)
    except VerificationError as error:
        _repository_error(error)


@router.post('/{project_id}/verifications')
async def reserve_verification(project: OwnedProject, request: Request):
    require_auth_origin(request)
    settings, _client = _configured(request)
    request_id = await _request_id(request)
    if project.status != 'ready':
        _deny(409, '项目尚未准备好验证')
    repository = VerificationRepository(settings.db_path)
    try:
        scope = await asyncio.to_thread(repository.current_scope,
                                        owner=project.user_id, project_id=project.id)
        reserved = await asyncio.to_thread(repository.reserve, owner=project.user_id,
            workspace_id=scope.workspace_id, request_id=request_id,
            expected_revision=scope.revision_id, expected_contract=scope.contract_digest,
            policy_digest=settings.verifier_policy_digest,
            runner_version=settings.verifier_runner_version,
            budget_seconds=settings.verifier_budget_seconds)
        return JSONResponse(_view(VerificationState(reserved, None, False)),
                            headers=_HEADERS)
    except VerificationError as error:
        _repository_error(error)


@router.get('/{project_id}/verifications/{request_id}')
async def verification_status(project: OwnedProject, request_id: str,
                              request: Request):
    require_console_host(request)
    settings, _client = _configured(request)
    if _REQUEST_ID.fullmatch(request_id) is None:
        _deny(404, '验证请求不存在')
    repository = VerificationRepository(settings.db_path)
    state = await _describe(repository, project.user_id, project.id, request_id)
    return JSONResponse(_view(state), headers=_HEADERS)


@router.post('/{project_id}/verifications/{request_id}/run')
async def run_verification(project: OwnedProject, request_id: str,
                           request: Request):
    require_auth_origin(request)
    settings, client = _configured(request)
    if (request.scope.get('query_string')
            or any(key.lower() in (b'content-encoding',b'transfer-encoding')
                   for key, _ in request.scope['headers'])
            or any(key.lower() == b'content-length' and value != b'0'
                   for key, value in request.scope['headers'])):
        _deny(400, '验证执行不接受请求内容')
    if _REQUEST_ID.fullmatch(request_id) is None:
        _deny(404, '验证请求不存在')
    repository = VerificationRepository(settings.db_path)
    before = await _describe(repository, project.user_id, project.id, request_id)
    if before.result is not None:
        return JSONResponse(_view(before), headers=_HEADERS)
    if before.dispatched or before.request.deadline <= time.time():
        return JSONResponse(_view(before), status_code=202, headers=_HEADERS)
    try:
        response = await client.verify(owner=project.user_id, request_id=request_id)
    except VerifierClientError as error:
        if error.code == 'verifier_busy':
            _deny(503, '验证服务繁忙，请稍后查询状态')
        after = await _describe(repository, project.user_id, project.id, request_id)
        if after.result is not None:
            return JSONResponse(_view(after), headers=_HEADERS)
        if error.code in ('verifier_outcome_unknown', 'verifier_already_dispatched'):
            return JSONResponse(_view(after), status_code=202, headers=_HEADERS)
        if error.code in ('verification_expired','verification_stale_contract',
                          'verification_stale_artifact','verification_stale_evidence'):
            _deny(409, '当前版本或需求已变化，请重新预约验证')
        _deny(503, '验证服务暂不可用，请查询状态')
    after = await _describe(repository, project.user_id, project.id, request_id)
    result = after.result
    if (result is None or result.request_id != response.request_id
            or result.revision_id != response.revision_id
            or result.outcome != response.outcome
            or result.total != response.total or result.passed != response.passed):
        _deny(503, '验证结果暂不可确认，请查询状态')
    return JSONResponse(_view(after), headers=_HEADERS)
