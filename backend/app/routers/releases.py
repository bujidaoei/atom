"""Owner-scoped verified release control; never reads a mutable workspace."""
from __future__ import annotations

import asyncio
import json
import re
import ssl

from fastapi import APIRouter, HTTPException, Request
from starlette.requests import ClientDisconnect

from ..artifacts import ArtifactError
from ..bounded_operations import OwnedJSONResponse
from ..config import get_settings
from ..console_auth import require_auth_origin, require_console_host
from ..content_hosts import ContentHosts
from ..ip_ingress import IngressError, probe_ip_routes
from ..project_origins import OriginRoute, ProjectOriginError, ProjectOriginRepository
from ..project_site_url import public_project_url
from ..deps import OwnedProject
from ..release_repository import ReleaseRepository
from ..release_history import publication_history
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


async def _command(request: Request, verification_mode='required'):
    command = await _json_command(request)
    fields = {'releaseId', 'expectedRevision', 'expectedGeneration', 'audience', 'slug'}
    expected_fields = fields | {'verificationId'} if verification_mode == 'required' else fields
    if verification_mode == 'advisory' and command.get('verificationId') is None:
        command.pop('verificationId', None)
    if (type(command) is not dict
            or set(command) != expected_fields
            or type(command['releaseId']) is not str or _ID.fullmatch(command['releaseId']) is None
            or (verification_mode == 'required' and
                (type(command['verificationId']) is not str or _ID.fullmatch(command['verificationId']) is None))
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


async def _rollback_command(request: Request):
    command = await _json_command(request)
    if (set(command) != {'commandId', 'newReleaseId', 'sourceReleaseId',
                         'expectedGeneration', 'expectedRevision'}
            or any(type(command[key]) is not str or _ID.fullmatch(command[key]) is None
                   for key in ('commandId', 'newReleaseId'))
            or any(type(command[key]) is not str or _REVISION.fullmatch(command[key]) is None
                   for key in ('sourceReleaseId', 'expectedRevision'))
            or type(command['expectedGeneration']) is not int
            or not 1 <= command['expectedGeneration'] < 2**63-1):
        _deny(400, '恢复请求格式不正确')
    return command


def _ip_project_url(settings, project_id: str) -> str:
    try:
        return public_project_url(settings.db_path, project_id=project_id,
            address=settings.ip_preview_address,
            first_port=settings.ip_preview_first_port,
            last_port=settings.ip_preview_last_port)
    except ProjectOriginError:
        _deny(503, '项目网站地址暂不可用')


def _configured(request: Request, project_id: str):
    settings = get_settings()
    if (settings.sandbox_mode != 'broker' or settings.session_mode != 'durable'
            or (settings.publication_verification == 'required' and settings.verifier_origin is None)
            or (settings.content_host_suffix is None and not settings.ip_public_enabled)):
        _deny(404, '发布服务暂未就绪')
    if settings.ip_public_enabled:
        _ip_project_url(settings, project_id)
    resources = getattr(request.app.state, 'execution', None)
    if resources is None:
        _deny(503, '发布服务暂不可用')
    return settings, resources.store


def _ip_readiness(settings, project_id: str):
    if not settings.ip_public_enabled:
        return None

    def check():
        try:
            origins = ProjectOriginRepository(settings.db_path,
                first_port=settings.ip_preview_first_port,
                last_port=settings.ip_preview_last_port)
            pair = origins.for_project(project_id)
            if pair is None:
                raise IngressError('ingress_origin_missing')
            context = ssl.create_default_context(
                cafile=str(settings.ip_ingress_ca_file) if settings.ip_ingress_ca_file else None)
            probe_ip_routes((OriginRoute(project_id, 'preview', pair.preview_port),
                             OriginRoute(project_id, 'public', pair.public_port)),
                            settings.ip_preview_address, tls_context=context,
                            timeout_seconds=3)
        except IngressError:
            raise
        except (ProjectOriginError, OSError, ValueError):
            raise IngressError('ingress_probe_unavailable') from None

    return check


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
    settings, store = _configured(request, project.id)
    command = await _command(request, settings.publication_verification)
    lifecycle = request.app.state.release_operations
    token = lifecycle.acquire()
    if token is None:
        _deny(503, '发布服务繁忙')
    release = True
    try:
        def apply():
            required = settings.publication_verification == 'required'
            receipt = ReleaseRepository(settings.db_path,
                required_schema='verified' if required else 16).publish_snapshot(store,
                verification_mode=settings.publication_verification,
                readiness=_ip_readiness(settings, project.id),
                owner=project.user_id, project_id=project.id,
                release_id=command['releaseId'], verification_id=command.get('verificationId'),
                expected_revision=command['expectedRevision'],
                expected_generation=command['expectedGeneration'],
                policy_digest=settings.verifier_policy_digest if required else None,
                runner_version=settings.verifier_runner_version if required else None,
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
    except IngressError:
        response = OwnedJSONResponse({'detail':'项目网站尚未就绪，请稍后重试'}, lifecycle, token,
                                     status_code=503, headers=_HEADERS)
        release = False
        return response
    except (VerificationError, ArtifactError) as error:
        response = OwnedJSONResponse({'detail':'发布结果暂时无法确认'}, lifecycle, token,
                                     status_code=_status(error), headers=_HEADERS)
        release = False
        return response
    finally:
        if release:
            lifecycle.release(token)


@router.get('/{project_id}/releases/current')
async def current_release(project: OwnedProject, request: Request):
    settings, _store = _configured(request, project.id)
    require_console_host(request)
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
            lambda: ReleaseRepository(settings.db_path, required_schema='verified').current(
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
            if settings.ip_public_enabled:
                public_url = _ip_project_url(settings, project.id)
                pinned_url = public_url if pointer.live and pointer.audience == 'public' else None
                sharing_url = pinned_url
            else:
                hosts = ContentHosts(settings.content_host_suffix)
                pinned_url = hosts.url(pointer.binding_id) if pointer.live else None
                sharing_url = (hosts.sharing_url(pointer.slug)
                               if pointer.live and pointer.audience == 'public' else None)
            result = {'publication':{
                'releaseId':pointer.release_id, 'revisionId':pointer.revision_id,
                'verificationId':pointer.verification_id,
                'verificationMode':pointer.verification_mode,
                'contractDigest':pointer.contract_digest,
                'policyDigest':pointer.policy_digest,
                'audience':pointer.audience, 'slug':pointer.slug,
                'generation':pointer.generation, 'live':pointer.live,
                'bindingId':pointer.binding_id,
                'pinnedUrl':pinned_url, 'sharingUrl':sharing_url}}
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
    settings, _store = _configured(request, project.id)
    command = await _unpublish_command(request)
    lifecycle = request.app.state.release_operations
    token = lifecycle.acquire()
    if token is None:
        _deny(503, '发布服务繁忙')
    release = True
    try:
        def apply():
            receipt = ReleaseRepository(settings.db_path, required_schema='verified').unpublish(
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
        response = OwnedJSONResponse({'detail':'停止发布的结果暂时无法确认'}, lifecycle, token,
                                     status_code=_status(error), headers=_HEADERS)
        release = False
        return response
    finally:
        if release:
            lifecycle.release(token)


@router.post('/{project_id}/releases/{release_id}/rollback')
async def rollback_verified_release(project: OwnedProject, release_id: str, request: Request):
    require_auth_origin(request)
    if (request.headers.getlist('x-atom-intent') != ['rollback-verified-release']
            or _REVISION.fullmatch(release_id) is None):
        _deny(403, '恢复请求缺少必要信息')
    settings, store = _configured(request, project.id)
    command = await _rollback_command(request)
    lifecycle = request.app.state.release_operations
    token = lifecycle.acquire()
    if token is None:
        _deny(503, '发布服务繁忙')
    release = True
    try:
        def apply():
            required = settings.publication_verification == 'required'
            receipt = ReleaseRepository(settings.db_path,
                required_schema='verified' if required else 16).restore_snapshot(store,
                verification_mode=settings.publication_verification,
                readiness=_ip_readiness(settings, project.id),
                owner=project.user_id, project_id=project.id,
                command_id=command['commandId'], release_id=command['newReleaseId'],
                source_release_id=command['sourceReleaseId'], expected_release=release_id,
                expected_generation=command['expectedGeneration'],
                expected_revision=command['expectedRevision'],
                policy_digest=settings.verifier_policy_digest if required else None,
                runner_version=settings.verifier_runner_version if required else None)
            return {'releaseId':receipt.release_id,
                    'sourceReleaseId':receipt.source_release_id,
                    'displacedReleaseId':receipt.displaced_release_id,
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
    except IngressError:
        response = OwnedJSONResponse({'detail':'项目网站尚未就绪，请稍后重试'}, lifecycle, token,
                                     status_code=503, headers=_HEADERS)
        release = False
        return response
    except (VerificationError, ArtifactError) as error:
        response = OwnedJSONResponse({'detail':'恢复结果暂时无法确认'}, lifecycle, token,
                                     status_code=_status(error), headers=_HEADERS)
        release = False
        return response
    finally:
        if release:
            lifecycle.release(token)


@router.get('/{project_id}/releases/history')
async def release_history(project: OwnedProject, request: Request):
    settings, _store = _configured(request, project.id)
    require_console_host(request)
    query = request.query_params
    if (request.headers.getlist('x-atom-intent') != ['inspect-verified-release']
            or (request.headers.getlist('origin')
                and request.headers.getlist('origin') != [settings.console_origin])
            or any(key not in ('limit', 'cursor') for key in query)
            or any(len(query.getlist(key)) != 1 for key in query)
            or re.fullmatch(r'[0-9]{1,2}', query.get('limit', '20')) is None):
        _deny(400, '版本历史查询格式不正确')
    limit = int(query.get('limit', '20'))
    if not 1 <= limit <= 50:
        _deny(400, '每次最多读取 50 个发布版本')
    lifecycle = request.app.state.release_operations
    token = lifecycle.acquire()
    if token is None:
        _deny(503, '版本历史暂时繁忙，请稍后重试')
    release = True
    try:
        worker = asyncio.create_task(asyncio.to_thread(publication_history,
            settings.db_path, owner=project.user_id, project_id=project.id,
            limit=limit, cursor=query.get('cursor')))
        _WORKERS.add(worker)
        worker.add_done_callback(_WORKERS.discard)
        try:
            result = await asyncio.shield(worker)
        except asyncio.CancelledError:
            release = False
            worker.add_done_callback(lambda done: _finished(done, lifecycle, token))
            raise
        result['publicationPolicy'] = settings.publication_verification
        hosts = None if settings.ip_public_enabled else ContentHosts(settings.content_host_suffix)
        for snapshot in result['items']:
            snapshot['previewUrl'] = (None if hosts is None else
                hosts.url(snapshot['bindingId']) + '_atom/bootstrap')
        response = OwnedJSONResponse(result, lifecycle, token, headers=_HEADERS)
        release = False
        return response
    except VerificationError as error:
        response = OwnedJSONResponse({'detail': '暂时无法读取版本历史'}, lifecycle, token,
            status_code=400 if str(error) == 'invalid_release_request' else _status(error), headers=_HEADERS)
        release = False
        return response
    finally:
        if release:
            lifecycle.release(token)
