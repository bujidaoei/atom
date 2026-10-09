"""Standalone content ASGI service; no console credentials or API proxy."""
import asyncio
from dataclasses import dataclass
import json
import mimetypes
from threading import BoundedSemaphore

from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from .artifacts import ArtifactError
from .access_repository import AccessError
from .content_bootstrap import BOOTSTRAP_PATH, ContentNavigation, bootstrap_response
from .content_cookies import content_session_cookie
from .content_exchange import (EXCHANGE_PATH, EXCHANGE_HEADERS, ExchangeRequestError,
                               validate_exchange, receive_handoff, exchange_response)
from .content_policy import ContentPolicyError, is_control_path, GENERATED_CONTENT_HEADERS
from .content_hosts import ContentHostError
from .project_origins import ProjectOriginError
from .project_port_hosts import ProjectPortHosts
from .project_public_hosts import ProjectPublicHosts
from .ip_ingress import HEALTH_PATH
from .release_view import materialized_content, materialized_private_content
from .snapshots import SnapshotError
from .verification_repository import VerificationError

HEADERS = dict(GENERATED_CONTENT_HEADERS)


@dataclass(frozen=True)
class ContentLimits:
    active_responses: int = 8
    send_seconds: float = 10
    drain_seconds: float = 15
    receive_seconds: float = 5

    def __post_init__(self):
        if (type(self.active_responses) is not int or not 1 <= self.active_responses <= 32
                or any(isinstance(value, bool) or not isinstance(value, (int, float))
                       or not 0.01 <= value <= 60
                       for value in (self.send_seconds, self.drain_seconds, self.receive_seconds))):
            raise ValueError('invalid_content_limits')


class ContentService:
    def __init__(self, repository, store, hosts, *, limits: ContentLimits = ContentLimits(), access=None, navigation: ContentNavigation | None = None):
        if access is not None and access.path.resolve()!=repository.path.resolve():
            raise ValueError('content_access_database_mismatch')
        if navigation is not None:
            if access is None:raise ValueError('content_navigation_requires_access')
            navigation.validate_content_hosts(hosts)
        self.navigation=navigation
        self.repository, self.store, self.hosts = repository, store, hosts
        self.access=access
        self.limits = limits
        self._responses = BoundedSemaphore(limits.active_responses)
        self._reads = set()
        self._pending = set()
        self._draining = False

    def _read(self,binding,path,navigation,session_secret=None):
        parts = path.split('/')
        if (not path.startswith('/') or len(path)>4096 or '\\' in path or '\0' in path
            or any(part in ('.','..') for part in parts) or is_control_path(path)):
            return Response(status_code=404,headers=HEADERS)
        if session_secret is not None:
            if self.access is None:raise AccessError('content_access_denied')
            materialized=materialized_private_content(self.repository,self.access,self.store,
                binding_id=binding,session_secret=session_secret)
        else:
            materialized=materialized_content(self.repository,self.store,binding_id=binding)
        with materialized as view:
            target = view.path.joinpath(*parts[1:])
            if target.is_dir():target = target/'index.html'
            if not target.is_file() and navigation and '.' not in parts[-1]:
                target = view.path/'index.html'
            if not target.is_file():return Response(status_code=404,headers=HEADERS)
            media,_ = mimetypes.guess_type(target.name)
            return Response(target.read_bytes(),media_type=media or 'application/octet-stream',
                headers={**HEADERS,'X-Atom-Release':view.publication.release_id,'X-Atom-Revision':view.publication.revision_id})

    def _response(self, scope, handoff=None):
        method = scope.get('method')
        try:
            path = scope.get('path')
            if (isinstance(self.hosts, ProjectPublicHosts) and path == HEALTH_PATH):
                if (method not in ('GET', 'HEAD') or scope.get('scheme') != 'https'
                        or scope.get('query_string', b'')
                        or scope.get('raw_path', b'') != HEALTH_PATH.encode('ascii')):
                    response = Response(status_code=404, headers=HEADERS)
                else:
                    route = ProjectPortHosts(self.hosts.address, self.hosts.origins).route(
                        scope.get('headers', []), purpose='public')
                    body = json.dumps({'purpose':'public', 'projectId':route.project_id},
                                      sort_keys=True, separators=(',', ':'))
                    response = Response(body, media_type='application/json', headers=HEADERS)
            else:
                binding = self.hosts.route(scope.get('headers',[]))
                response = self._routed_response(scope, method, binding, handoff)
        except ExchangeRequestError as error:
            response=Response(status_code=error.status,headers={**EXCHANGE_HEADERS,**({'Allow':error.allow} if error.allow else {})})
        except ContentHostError:
            response = Response(status_code=404,headers=HEADERS)
        except ProjectOriginError:
            response = Response(status_code=503,headers=HEADERS)
        except AccessError as error:
            code=404 if str(error) in ('content_access_denied','session_not_found') else 503
            response=Response(status_code=code,headers=HEADERS)
        except VerificationError as error:
            code = 404 if str(error) in ('content_not_found','release_not_found') else 503
            response = Response(status_code=code,headers=HEADERS)
        except (ArtifactError,SnapshotError,ContentPolicyError,OSError):
            response = Response(status_code=503,headers=HEADERS)
        if method=='HEAD':
            response.body=b''
        return response

    def _routed_response(self, scope, method, binding, handoff):
        if self.navigation is not None and scope.get('path')==BOOTSTRAP_PATH:
            response=bootstrap_response(scope,self.hosts,self.access,self.navigation)
        elif self.access is not None and scope.get('path')==EXCHANGE_PATH:
            response=exchange_response(scope,self.hosts,self.access,handoff)
        elif method not in ('GET','HEAD'):
            response = Response(status_code=405,headers={**HEADERS,'Allow':'GET, HEAD'})
        elif binding is None:
            path = scope.get('path','/')
            if not path.startswith('/s/'):
                response = Response(status_code=404,headers=HEADERS)
            else:
                destination = self.repository.sharing_binding(slug=path[3:])
                response = Response(status_code=307,headers={**HEADERS,
                    'Location':self.hosts.url(destination.id)})
        else:
            # Browser navigation metadata is a fallback hint, never auth.
            navigation = any(k.lower()==b'sec-fetch-mode' and v==b'navigate' for k,v in scope['headers'])
            response = self._read(binding,scope.get('path','/'),navigation,
                content_session_cookie(scope.get('headers',[])))
        return response

    def _release(self, token):
        self._responses.release()
        self._pending.remove(token)
        token.set_result(None)

    def _finish_cancelled_read(self, task, token):
        try:
            # Retrieve any error; disconnected callers have no response channel.
            if not task.cancelled():
                task.exception()
        finally:
            self._release(token)

    async def _lifespan(self, receive, send):
        while True:
            message = await receive()
            if message['type'] == 'lifespan.startup':
                if self._draining:
                    await send({'type': 'lifespan.startup.failed', 'message': 'content_draining'})
                    return
                await send({'type': 'lifespan.startup.complete'})
            elif message['type'] == 'lifespan.shutdown':
                self._draining = True
                remaining = set()
                if self._pending:
                    # wait() does not cancel tokens on timeout. Their owners
                    # retain responsibility for actual resource completion.
                    _, remaining = await asyncio.wait(self._pending, timeout=self.limits.drain_seconds)
                if remaining:
                    await send({'type': 'lifespan.shutdown.failed', 'message': 'content_drain_timeout'})
                else:
                    await send({'type': 'lifespan.shutdown.complete'})
                return
            else:
                raise RuntimeError('invalid_content_lifespan')

    async def _send(self, response, scope, receive, send):
        async with asyncio.timeout(self.limits.send_seconds):
            await response(scope, receive, send)

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'lifespan':
            await self._lifespan(receive, send)
            return
        if scope['type'] != 'http':
            raise RuntimeError('content_http_only')
        if self._draining or not self._responses.acquire(blocking=False):
            await self._send(Response(status_code=503, headers=HEADERS), scope, receive, send)
            return
        token = asyncio.get_running_loop().create_future()
        self._pending.add(token)
        release_slot = True
        try:
            # Keep ownership independently of the caller: cancelling an asyncio
            # waiter cannot stop synchronous artifact IO in its worker thread.
            handoff=None
            if self.access is not None and scope.get('path')==EXCHANGE_PATH and scope.get('method')=='POST':
                try:
                    validate_exchange(scope,self.hosts)
                    async with asyncio.timeout(self.limits.receive_seconds):
                        handoff=await receive_handoff(receive)
                except (ExchangeRequestError,ContentHostError,AccessError,TimeoutError) as error:
                    status=(error.status if isinstance(error,ExchangeRequestError) else
                            408 if isinstance(error,TimeoutError) else 404)
                    await self._send(Response(status_code=status,headers=EXCHANGE_HEADERS),scope,receive,send)
                    return
            read = asyncio.create_task(run_in_threadpool(self._response, scope, handoff))
            self._reads.add(read)
            read.add_done_callback(self._reads.discard)
            try:
                response = await asyncio.shield(read)
            except asyncio.CancelledError:
                release_slot = False
                read.add_done_callback(lambda task: self._finish_cancelled_read(task, token))
                raise
            await self._send(response, scope, receive, send)
        finally:
            if release_slot:
                self._release(token)
