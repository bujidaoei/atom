"""Authenticated console handoff issuance; no caller-selected redirect target."""
import asyncio
import json
import re
from threading import BoundedSemaphore

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.requests import ClientDisconnect

from ..access_repository import AccessError
from ..config import get_settings
from ..console_auth import credentials, request_session_token, require_auth_origin, require_console_host
from ..content_access import ContentAccessRepository
from ..content_hosts import ContentHosts

router = APIRouter(prefix='/content-access', tags=['content-access'])
_HEADERS = {'Cache-Control':'no-store', 'Referrer-Policy':'no-referrer'}
_ADMISSION = BoundedSemaphore(8)
_WORKERS = set()


def _deny(status):
    raise HTTPException(status, '无法签发私有访问凭据', headers=_HEADERS)


def _fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_field')
        result[key] = value
    return result


async def _read(request):
    payload = bytearray()
    count = 0
    async with asyncio.timeout(5):
        async for chunk in request.stream():
            count += 1
            if count > 128 or len(payload) + len(chunk) > 256:
                _deny(413)
            payload.extend(chunk)
    if len(payload) != int(request.headers['content-length']):
        _deny(400)
    try:
        body = json.loads(payload.decode('utf-8'), object_pairs_hook=_fields)
    except (ValueError, UnicodeError, RecursionError):
        _deny(400)
    return _validate_body(body)


def _validate_body(body):
    if (not isinstance(body, dict) or set(body) != {'binding','challenge'}
            or not isinstance(body['binding'], str) or re.fullmatch(r'[0-9a-f]{32}', body['binding']) is None
            or not isinstance(body['challenge'], str) or re.fullmatch(r'[0-9a-f]{64}', body['challenge']) is None):
        _deny(400)
    return body


def _issue(token, body, suffix):
    codec = credentials()
    source = codec.authenticate(token)
    if source is None:
        _deny(401)
    access = ContentAccessRepository(codec.repository.path)
    handoff = access.issue_handoff(viewer_id=source.user_id, source_session_id=source.id,
                                  binding_id=body['binding'], challenge=body['challenge'])
    return {'url':ContentHosts(suffix).url(body['binding']) + '_atom/exchange#' + handoff.secret,
            'expiresAt':handoff.expires_at}


def _describe(token, body, _suffix):
    codec = credentials()
    source = codec.authenticate(token)
    if source is None:
        _deny(401)
    return ContentAccessRepository(codec.repository.path).describe_handoff(
        viewer_id=source.user_id,source_session_id=source.id,
        binding_id=body['binding'],challenge=body['challenge'])


def _detached_done(worker):
    try:
        if not worker.cancelled():
            worker.exception()
    finally:
        _ADMISSION.release()


@router.post('/handoff')
async def handoff(request: Request):
    return await _handle(request,read_only=False)


@router.get('/request')
async def inspect_request(request: Request):
    return await _handle(request,read_only=True)


async def _handle(request,*,read_only):
    settings = get_settings()
    if settings.session_mode != 'durable' or settings.content_host_suffix is None:
        _deny(404)
    try:
        if read_only:
            require_console_host(request)
            origins=request.headers.getlist('origin')
            if origins and origins != [settings.console_origin]:
                _deny(403)
            if request.headers.getlist('x-atom-intent') != ['inspect-private-content']:
                _deny(403)
            if len(request.scope.get('query_string',b''))>256:
                _deny(400)
            items=request.query_params.multi_items()
            if len(items)!=2 or len(dict(items))!=2:
                _deny(400)
            body=_validate_body(dict(items))
        else:
            require_auth_origin(request)
            if request.headers.getlist('x-atom-intent') != ['open-private-content']:
                _deny(403)
            if request.headers.getlist('content-type') != ['application/json']:
                _deny(415)
            lengths = request.headers.getlist('content-length')
            if (len(lengths) != 1 or re.fullmatch(r'[0-9]{1,3}', lengths[0]) is None
                    or not 1 <= int(lengths[0]) <= 256 or request.url.query
                    or request.headers.getlist('content-encoding') or request.headers.getlist('transfer-encoding')):
                _deny(400)
        token = request_session_token(request)
        if token is None:
            _deny(401)
        if not _ADMISSION.acquire(blocking=False):
            _deny(503)
        release = True
        try:
            if not read_only:
                body = await _read(request)
            operation = _describe if read_only else _issue
            worker = asyncio.create_task(run_in_threadpool(operation, token, body, settings.content_host_suffix))
            _WORKERS.add(worker)
            worker.add_done_callback(_WORKERS.discard)
            try:
                result = await asyncio.shield(worker)
            except asyncio.CancelledError:
                release = False
                worker.add_done_callback(_detached_done)
                raise
            return JSONResponse(result, headers=_HEADERS)
        finally:
            if release:
                _ADMISSION.release()
    except ClientDisconnect:
        _deny(400)
    except TimeoutError:
        _deny(408)
    except AccessError as error:
        _deny(404 if str(error) == 'content_access_denied' else
              409 if str(error) == 'access_conflict' else
              429 if str(error) == 'content_access_capacity' else 503)
    except HTTPException as error:
        error.headers = {**(error.headers or {}), **_HEADERS}
        raise
