"""Authenticated bounded audit inspection; scope never comes from a caller account id."""
import asyncio
import re

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from ..access_repository import AccessError, AccessRepository
from ..audit_repository import AuditRepository, AuditReadError
from ..bounded_operations import OwnedJSONResponse
from ..config import get_settings
from ..console_auth import credentials, request_session_token, require_console_host

router = APIRouter(prefix='/audit', tags=['audit'])
_HEADERS = {'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'}
_WORKERS = set()
_DETAIL = '无法读取审计记录'


def _query(request):
    if len(request.scope.get('query_string', b'')) > 256:
        raise HTTPException(400, _DETAIL)
    pairs = request.query_params.multi_items()
    values = dict(pairs)
    if len(values) != len(pairs) or set(values) - {'project', 'after', 'upper', 'limit'}:
        raise HTTPException(400, _DETAIL)
    result = {}
    for key in ('after', 'upper', 'limit'):
        if key in values:
            value = values[key]
            if re.fullmatch(r'0|[1-9][0-9]{0,18}', value) is None or int(value) >= 2**63:
                raise HTTPException(400, _DETAIL)
            result[key] = int(value)
    if (not 1 <= result.get('limit', 50) <= 100 or
            result.get('after', 0) > result.get('upper', 0)):
        raise HTTPException(400, _DETAIL)
    if 'project' in values:
        try:
            AccessRepository._user(values['project'])
        except AccessError:
            raise HTTPException(400, _DETAIL) from None
        result['project_id'] = values['project']
    return result


def _read(token, query):
    codec = credentials()
    source = codec.authenticate(token)
    if source is None:
        raise HTTPException(401, _DETAIL)
    page = AuditRepository(codec.repository.path).page(
        user_id=source.user_id, source_session_id=source.id, **query)
    return {'events': page.events, 'upper': page.upper, 'nextAfter': page.next_after}


def _finished(worker, owner, admission):
    try:
        if not worker.cancelled():
            worker.exception()
    finally:
        owner.release(admission)


@router.get('/events')
async def events(request: Request):
    owner = request.app.state.audit_reads
    admission = None
    release = True
    try:
        settings = get_settings()
        if settings.session_mode != 'durable':
            raise HTTPException(404, _DETAIL)
        require_console_host(request)
        origins = request.headers.getlist('origin')
        if ((origins and origins != [settings.console_origin]) or
                request.headers.getlist('x-atom-intent') != ['inspect-audit-events']):
            raise HTTPException(403, _DETAIL)
        query = _query(request)
        token = request_session_token(request)
        if token is None:
            raise HTTPException(401, _DETAIL)
        admission = owner.acquire()
        if admission is None:
            raise HTTPException(503, _DETAIL)
        worker = asyncio.create_task(run_in_threadpool(_read, token, query))
        _WORKERS.add(worker)
        worker.add_done_callback(_WORKERS.discard)
        try:
            result = await asyncio.shield(worker)
        except asyncio.CancelledError:
            release = False
            worker.add_done_callback(lambda done: _finished(done, owner, admission))
            raise
        response = OwnedJSONResponse(result, owner, admission, headers=_HEADERS)
        release = False
        return response
    except (HTTPException, AccessError, AuditReadError) as error:
        status = (error.status_code if isinstance(error, HTTPException) else
                  404 if str(error) == 'audit_access_denied' else
                  400 if str(error) == 'invalid_audit_page' else 503)
        if admission is None:
            raise HTTPException(status, _DETAIL, headers=_HEADERS) from None
        response = OwnedJSONResponse({'detail': _DETAIL}, owner, admission,
                                     status_code=status, headers=_HEADERS)
        release = False
        return response
    finally:
        if release and admission is not None:
            owner.release(admission)
