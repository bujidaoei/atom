"""Owner-scoped verified release control; never reads a mutable workspace."""
from __future__ import annotations

import asyncio
import json
import re

from fastapi import APIRouter, HTTPException, Request
from starlette.requests import ClientDisconnect

from ..artifacts import ArtifactError
from ..bounded_operations import OwnedJSONResponse
from ..config import get_settings
from ..console_auth import require_auth_origin, require_console_host
from ..content_hosts import ContentHosts
from ..deps import OwnedProject
from ..release_repository import ReleaseRepository
from ..verification_repository import VerificationError


router = APIRouter(prefix='/projects', tags=['releases'])
_HEADERS = {'Cache-Control':'no-store', 'Referrer-Policy':'no-referrer'}
_ID = re.compile(r'[0-9a-f]{32}\Z')
_REVISION = re.compile(r'[A-Za-z0-9_.-]{1,100}\Z')
_SLUG = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*\Z')
_WORKERS = set()


def _deny(status: int, detail: str):
    raise HTTPException(status, detail, headers=_HEADERS)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_key')
        result[key] = value
    return result


async def _json_command(request: Request):
    headers = request.scope['headers']
    lengths = [value for key, value in headers if key.lower() == b'content-length']
    if (request.scope.get('query_string')
            or [value.lower() for key, value in headers if key.lower() == b'content-type']
               != [b'application/json']
            or len(lengths) != 1 or re.fullmatch(rb'[0-9]{1,3}', lengths[0]) is None
            or not 1 <= int(lengths[0]) <= 512
            or any(key.lower() in (b'content-encoding', b'transfer-encoding')
                   for key, _ in headers)):
        _deny(400, '发布请求格式不正确')
    body = bytearray()
    try:
        async with asyncio.timeout(5):
            async for chunk in request.stream():
                if len(body) + len(chunk) > 512:
                    _deny(413, '发布请求过大')
                body.extend(chunk)
    except (TimeoutError, ClientDisconnect):
        _deny(400, '发布请求未完整送达')
    if len(body) != int(lengths[0]):
        _deny(400, '发布请求未完整送达')
    try:
        command = json.loads(body.decode('utf-8'), object_pairs_hook=_unique,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, RecursionError):
        _deny(400, '发布请求格式不正确')
    if type(command) is not dict:
        _deny(400, '发布请求格式不正确')
    return command


async def _command(request: Request):
    command = await _json_command(request)
    if (type(command) is not dict
            or set(command) != {'releaseId', 'verificationId', 'expectedRevision',
                                'expectedGeneration', 'audience', 'slug'}
            or any(type(command[key]) is not str or _ID.fullmatch(command[key]) is None
                   for key in ('releaseId', 'verificationId'))
            or type(command['expectedRevision']) is not str
            or _REVISION.fullmatch(command['expectedRevision']) is None
            or type(command['expectedGeneration']) is not int
            or not 0 <= command['expectedGeneration'] < 2**63-1
            or command['audience'] not in ('owner', 'public')
            or type(command['slug']) is not str or len(command['slug']) > 63
            or _SLUG.fullmatch(command['slug']) is None):
        _deny(400, '发布请求格式不正确')
    return command


async def _unpublish_command(request: Request):
    command = await _json_command(request)
    if (set(command) != {'commandId', 'expectedGeneration'}
            or type(command['commandId']) is not str
            or _ID.fullmatch(command['commandId']) is None
            or type(command['expectedGeneration']) is not int
            or not 1 <= command['expectedGeneration'] < 2**63-1):
        _deny(400, '撤销请求格式不正确')
    return command


def _configured(request: Request):
    settings = get_settings()
    if (settings.sandbox_mode != 'broker' or settings.session_mode != 'durable'
            or settings.verifier_origin is None or settings.content_host_suffix is None):
        _deny(404, '可信发布尚未启用')
    resources = getattr(request.app.state, 'execution', None)
    if resources is None:
        _deny(503, '发布服务暂不可用')
    return settings, resources.store


def _status(error: VerificationError | ArtifactError) -> int:
    code = str(error)
    if code in ('release_not_found', 'verification_not_found'):
        return 404
    if code in ('release_conflict', 'release_evidence_required', 'release_stale_evidence',
                'release_untrusted_evidence', 'invalid_stored_contract',
                'release_artifact_required', 'release_artifact_mismatch',
                'invalid_release_request'):
        return 409
    return 503


def _finished(worker, lifecycle, token):
    try:
        if not worker.cancelled():
            worker.exception()
    finally:
        lifecycle.release(token)


@router.post('/{project_id}/releases')
async def publish_verified_release(project: OwnedProject, request: Request):
    require_auth_origin(request)
    if request.headers.getlist('x-atom-intent') != ['publish-verified-release']:
        _deny(403, '发布意图不明确')
    settings, store = _configured(request)
    command = await _command(request)
    lifecycle = request.app.state.release_operations
    token = lifecycle.acquire()
    if token is None:
        _deny(503, '发布服务繁忙')
    release = True
    try:
        def apply():
            receipt = ReleaseRepository(settings.db_path, required_schema=13).publish_verified(store,
                owner=project.user_id, project_id=project.id,
                release_id=command['releaseId'], verification_id=command['verificationId'],
                expected_revision=command['expectedRevision'],
                expected_generation=command['expectedGeneration'],
                policy_digest=settings.verifier_policy_digest,
                runner_version=settings.verifier_runner_version,
                audience=command['audience'], slug=command['slug'])
            return {'releaseId':receipt.release_id, 'revisionId':receipt.revision_id,
                    'generation':receipt.generation, 'slug':receipt.slug}
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
    except (VerificationError, ArtifactError) as error:
        response = OwnedJSONResponse({'detail':'无法确认可信发布'}, lifecycle, token,
                                     status_code=_status(error), headers=_HEADERS)
        release = False
        return response
    finally:
        if release:
            lifecycle.release(token)


@router.get('/{project_id}/releases/current')
async def current_release(project: OwnedProject, request: Request):
    require_console_host(request)
    settings, _store = _configured(request)
    if (request.scope.get('query_string')
            or request.headers.getlist('x-atom-intent') != ['inspect-verified-release']
            or (request.headers.getlist('origin')
                and request.headers.getlist('origin') != [settings.console_origin])):
        _deny(400, '发布查询格式不正确')
    lifecycle = request.app.state.release_operations
    token = lifecycle.acquire()
    if token is None:
        _deny(503, '发布服务繁忙')
    release = True
    try:
        worker = asyncio.create_task(asyncio.to_thread(
            lambda: ReleaseRepository(settings.db_path, required_schema=13).current(
                owner=project.user_id, project_id=project.id)))
        _WORKERS.add(worker)
        worker.add_done_callback(_WORKERS.discard)
        try:
            pointer = await asyncio.shield(worker)
        except asyncio.CancelledError:
            release = False
            worker.add_done_callback(lambda done: _finished(done, lifecycle, token))
            raise
        if pointer is None:
            result = {'publication':None}
        else:
            hosts = ContentHosts(settings.content_host_suffix)
            result = {'publication':{
                'releaseId':pointer.release_id, 'revisionId':pointer.revision_id,
                'verificationId':pointer.verification_id,
                'contractDigest':pointer.contract_digest,
                'policyDigest':pointer.policy_digest,
                'audience':pointer.audience, 'slug':pointer.slug,
                'generation':pointer.generation, 'live':pointer.live,
                'bindingId':pointer.binding_id,
                'pinnedUrl':hosts.url(pointer.binding_id) if pointer.live else None,
                'sharingUrl':hosts.sharing_url(pointer.slug)
                    if pointer.live and pointer.audience == 'public' else None}}
        response = OwnedJSONResponse(result, lifecycle, token, headers=_HEADERS)
        release = False
        return response
    except VerificationError as error:
        response = OwnedJSONResponse({'detail':'无法读取发布状态'}, lifecycle, token,
                                     status_code=_status(error), headers=_HEADERS)
        release = False
        return response
    finally:
        if release:
            lifecycle.release(token)


@router.post('/{project_id}/releases/{release_id}/unpublish')
async def unpublish_verified_release(project: OwnedProject, release_id: str, request: Request):
    require_auth_origin(request)
    if (request.headers.getlist('x-atom-intent') != ['unpublish-verified-release']
            or _ID.fullmatch(release_id) is None):
        _deny(403, '撤销意图不明确')
    settings, _store = _configured(request)
    command = await _unpublish_command(request)
    lifecycle = request.app.state.release_operations
    token = lifecycle.acquire()
    if token is None:
        _deny(503, '发布服务繁忙')
    release = True
    try:
        def apply():
            receipt = ReleaseRepository(settings.db_path, required_schema=13).unpublish(
                owner=project.user_id, project_id=project.id,
                command_id=command['commandId'], expected_release=release_id,
                expected_generation=command['expectedGeneration'],
                require_verified_schema=True)
            return {'commandId': receipt.command_id, 'releaseId': receipt.release_id,
                    'generation': receipt.generation}
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
    except VerificationError as error:
        response = OwnedJSONResponse({'detail':'无法确认可信撤销'}, lifecycle, token,
                                     status_code=_status(error), headers=_HEADERS)
        release = False
        return response
    finally:
        if release:
            lifecycle.release(token)
