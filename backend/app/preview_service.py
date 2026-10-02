"""Standalone owner-preview ASGI service with no console API authority."""
import asyncio
from datetime import datetime, timezone
import mimetypes
from threading import BoundedSemaphore

from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from .artifacts import ArtifactError
from .content_exchange import ExchangeRequestError, receive_handoff
from .content_hosts import ContentHostError
from .content_policy import ContentPolicyError, is_control_path
from .content_service import ContentLimits, HEADERS
from .preview_access import PreviewAccessError, PreviewAccessRepository
from .preview_cookie import preview_cookie, preview_cookie_name
from .preview_exchange import EXCHANGE_HEADERS, EXCHANGE_PATH, OPEN_PATH, PAGE
from .preview_view import materialized_preview
from .project_origins import ProjectOriginError
from .project_port_hosts import ProjectPortHosts
from .snapshots import SnapshotError

PREVIEW_HEADERS = {**HEADERS, 'Cross-Origin-Opener-Policy': 'same-origin'}


class PreviewService:
    def __init__(self, access: PreviewAccessRepository, store, hosts: ProjectPortHosts, *,
                 limits: ContentLimits = ContentLimits()):
        if access.path.resolve() != hosts.origins.path.resolve():
            raise ValueError('preview_database_mismatch')
        self.access, self.store, self.hosts, self.limits = access, store, hosts, limits
        self._responses = BoundedSemaphore(limits.active_responses)
        self._pending = set()
        self._reads = set()
        self._draining = False

    @staticmethod
    def _one(headers, name):
        values = [value for key, value in headers if key.lower() == name]
        if len(values) != 1:
            raise ExchangeRequestError(400)
        return values[0]

    def _validate_control(self, scope, route):
        path = scope.get('path')
        if (scope.get('scheme') != 'https' or scope.get('query_string', b'')
                or scope.get('raw_path', path.encode()) != path.encode()):
            raise ExchangeRequestError(400)
        if path == OPEN_PATH:
            if scope['method'] not in ('GET', 'HEAD'):
                raise ExchangeRequestError(405, allow='GET, HEAD')
        elif path == EXCHANGE_PATH:
            if scope['method'] != 'POST':
                raise ExchangeRequestError(405, allow='POST')
            headers = scope.get('headers', [])
            if self._one(headers, b'origin') != self.hosts.origin(route.port).encode('ascii'):
                raise ExchangeRequestError(403)
            if self._one(headers, b'content-type') != b'application/octet-stream':
                raise ExchangeRequestError(415)
            if self._one(headers, b'content-length') != b'64':
                raise ExchangeRequestError(400)
            if any(key.lower() in (b'content-encoding', b'transfer-encoding')
                   for key, _ in headers):
                raise ExchangeRequestError(400)
        else:
            raise ExchangeRequestError(404)

    def _read(self, route, scope):
        path = scope.get('path', '/')
        parts = path.split('/')
        if (not path.startswith('/') or len(path) > 4096 or '\\' in path or '\0' in path
                or any(part in ('.', '..') for part in parts) or is_control_path(path)):
            return Response(status_code=404, headers=PREVIEW_HEADERS)
        secret = preview_cookie(scope.get('headers', []), port=route.port)
        if secret is None:
            return Response(status_code=404, headers=PREVIEW_HEADERS)
        with materialized_preview(self.access, self.store,
                                  project_id=route.project_id, session_secret=secret) as view:
            target = view.path.joinpath(*parts[1:])
            if target.is_dir():
                target = target / 'index.html'
            navigation = any(key.lower() == b'sec-fetch-mode' and value == b'navigate'
                             for key, value in scope.get('headers', []))
            if not target.is_file() and navigation and '.' not in parts[-1]:
                target = view.path / 'index.html'
            if not target.is_file():
                return Response(status_code=404, headers=PREVIEW_HEADERS)
            media, _ = mimetypes.guess_type(target.name)
            return Response(target.read_bytes(), media_type=media or 'application/octet-stream',
                            headers={**PREVIEW_HEADERS, 'X-Atom-Revision': view.revision.revision_id})

    def _response(self, scope, handoff=None):
        method = scope.get('method')
        try:
            route = self.hosts.route(scope.get('headers', []), purpose='preview')
            if scope.get('scheme') != 'https':
                raise ContentHostError('insecure_preview_transport')
            path = scope.get('path', '/')
            if path in (OPEN_PATH, EXCHANGE_PATH):
                self._validate_control(scope, route)
                if path == OPEN_PATH:
                    response = Response(PAGE, media_type='text/html', headers=EXCHANGE_HEADERS)
                else:
                    session = self.access.exchange(project_id=route.project_id, handoff=handoff)
                    response = Response(status_code=204, headers=EXCHANGE_HEADERS)
                    response.set_cookie(preview_cookie_name(route.port), session.secret,
                                        path='/', secure=True, httponly=True, samesite='lax',
                                        expires=datetime.fromtimestamp(session.expires_at, timezone.utc))
            elif method not in ('GET', 'HEAD'):
                response = Response(status_code=405, headers={**PREVIEW_HEADERS, 'Allow': 'GET, HEAD'})
            else:
                response = self._read(route, scope)
        except ExchangeRequestError as error:
            response = Response(status_code=error.status,
                                headers={**EXCHANGE_HEADERS,
                                         **({'Allow': error.allow} if error.allow else {})})
        except ContentHostError:
            response = Response(status_code=404, headers=PREVIEW_HEADERS)
        except ProjectOriginError:
            response = Response(status_code=503, headers=PREVIEW_HEADERS)
        except PreviewAccessError as error:
            code = (404 if str(error) in ('preview_access_denied', 'invalid_preview_request') else
                    429 if str(error) == 'preview_capacity' else 503)
            response = Response(status_code=code, headers=PREVIEW_HEADERS)
        except (ArtifactError, SnapshotError, ContentPolicyError, OSError):
            response = Response(status_code=503, headers=PREVIEW_HEADERS)
        if method == 'HEAD':
            response.body = b''
        return response

    async def _lifespan(self, receive, send):
        while True:
            message = await receive()
            if message['type'] == 'lifespan.startup':
                if self._draining:
                    await send({'type': 'lifespan.startup.failed', 'message': 'preview_draining'})
                    return
                await send({'type': 'lifespan.startup.complete'})
            elif message['type'] == 'lifespan.shutdown':
                self._draining = True
                if self._pending:
                    _, remaining = await asyncio.wait(self._pending,
                                                      timeout=self.limits.drain_seconds)
                else:
                    remaining = set()
                if remaining:
                    await send({'type': 'lifespan.shutdown.failed',
                                'message': 'preview_drain_timeout'})
                else:
                    await send({'type': 'lifespan.shutdown.complete'})
                return
            else:
                raise RuntimeError('invalid_preview_lifespan')

    def _release(self, token):
        self._responses.release()
        self._pending.remove(token)
        token.set_result(None)

    def _finish_cancelled(self, task, token):
        try:
            if not task.cancelled():
                task.exception()
        finally:
            self._release(token)

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'lifespan':
            await self._lifespan(receive, send)
            return
        if scope['type'] != 'http':
            raise RuntimeError('preview_http_only')
        if self._draining or not self._responses.acquire(blocking=False):
            await Response(status_code=503, headers=PREVIEW_HEADERS)(scope, receive, send)
            return
        token = asyncio.get_running_loop().create_future()
        self._pending.add(token)
        release_slot = True
        try:
            handoff = None
            if scope.get('path') == EXCHANGE_PATH and scope.get('method') == 'POST':
                try:
                    route = self.hosts.route(scope.get('headers', []), purpose='preview')
                    self._validate_control(scope, route)
                    async with asyncio.timeout(self.limits.receive_seconds):
                        handoff = await receive_handoff(receive)
                except (ExchangeRequestError, ContentHostError,
                        ProjectOriginError, TimeoutError) as error:
                    status = (error.status if isinstance(error, ExchangeRequestError) else
                              408 if isinstance(error, TimeoutError) else
                              503 if isinstance(error, ProjectOriginError) else 404)
                    await Response(status_code=status, headers=EXCHANGE_HEADERS)(scope, receive, send)
                    return
            read = asyncio.create_task(run_in_threadpool(self._response, scope, handoff))
            self._reads.add(read)
            read.add_done_callback(self._reads.discard)
            try:
                response = await asyncio.shield(read)
            except asyncio.CancelledError:
                release_slot = False
                read.add_done_callback(lambda done: self._finish_cancelled(done, token))
                raise
            async with asyncio.timeout(self.limits.send_seconds):
                await response(scope, receive, send)
        finally:
            if release_slot:
                self._release(token)
