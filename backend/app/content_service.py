"""Standalone public content ASGI service; no console credentials or API proxy."""
import asyncio
from dataclasses import dataclass
import mimetypes
from threading import BoundedSemaphore

from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from .artifacts import ArtifactError
from .content_hosts import ContentHostError
from .release_view import materialized_content
from .snapshots import SnapshotError
from .verification_repository import VerificationError

HEADERS = {
    'Cache-Control':'no-store',
    'X-Content-Type-Options':'nosniff',
    'Referrer-Policy':'no-referrer',
    'Content-Security-Policy':"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'none'; worker-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; sandbox allow-scripts allow-same-origin",
}


@dataclass(frozen=True)
class ContentLimits:
    active_responses: int = 1
    send_seconds: float = 10

    def __post_init__(self):
        if (type(self.active_responses) is not int or not 1 <= self.active_responses <= 32
                or isinstance(self.send_seconds, bool)
                or not isinstance(self.send_seconds, (int, float))
                or not 0.01 <= self.send_seconds <= 60):
            raise ValueError('invalid_content_limits')


class ContentService:
    def __init__(self, repository, store, hosts, *, limits: ContentLimits = ContentLimits()):
        self.repository, self.store, self.hosts = repository, store, hosts
        self.limits = limits
        self._responses = BoundedSemaphore(limits.active_responses)
        self._reads = set()

    def _read(self,binding,path,navigation):
        parts = path.split('/')
        if (not path.startswith('/') or len(path)>4096 or '\\' in path or '\0' in path
            or any(part in ('.','..') for part in parts)):
            return Response(status_code=404,headers=HEADERS)
        with materialized_content(self.repository,self.store,binding_id=binding) as view:
            target = view.path.joinpath(*parts[1:])
            if target.is_dir():target = target/'index.html'
            if not target.is_file() and navigation and '.' not in parts[-1]:
                target = view.path/'index.html'
            if not target.is_file():return Response(status_code=404,headers=HEADERS)
            media,_ = mimetypes.guess_type(target.name)
            return Response(target.read_bytes(),media_type=media or 'application/octet-stream',
                headers={**HEADERS,'X-Atom-Release':view.publication.release_id,'X-Atom-Revision':view.publication.revision_id})

    def _response(self, scope):
        method = scope.get('method')
        try:
            binding = self.hosts.binding(scope.get('headers',[]))
            if method not in ('GET','HEAD'):
                response = Response(status_code=405,headers={**HEADERS,'Allow':'GET, HEAD'})
            else:
                # Browser navigation metadata is a fallback hint, never auth.
                navigation = any(k.lower()==b'sec-fetch-mode' and v==b'navigate' for k,v in scope['headers'])
                response = self._read(binding,scope.get('path','/'),navigation)
        except ContentHostError:
            response = Response(status_code=404,headers=HEADERS)
        except VerificationError as error:
            code = 404 if str(error) in ('content_not_found','release_not_found') else 503
            response = Response(status_code=code,headers=HEADERS)
        except (ArtifactError,SnapshotError,OSError):
            response = Response(status_code=503,headers=HEADERS)
        if method=='HEAD':
            response.body=b''
        return response

    def _finish_cancelled_read(self, task):
        try:
            # Retrieve any error; disconnected callers have no response channel.
            if not task.cancelled():
                task.exception()
        finally:
            self._responses.release()

    async def _send(self, response, scope, receive, send):
        async with asyncio.timeout(self.limits.send_seconds):
            await response(scope, receive, send)

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            raise RuntimeError('content_http_only')
        if not self._responses.acquire(blocking=False):
            await self._send(Response(status_code=503, headers=HEADERS), scope, receive, send)
            return
        release_slot = True
        try:
            # Keep ownership independently of the caller: cancelling an asyncio
            # waiter cannot stop synchronous artifact IO in its worker thread.
            read = asyncio.create_task(run_in_threadpool(self._response, scope))
            self._reads.add(read)
            read.add_done_callback(self._reads.discard)
            try:
                response = await asyncio.shield(read)
            except asyncio.CancelledError:
                release_slot = False
                read.add_done_callback(self._finish_cancelled_read)
                raise
            await self._send(response, scope, receive, send)
        finally:
            if release_slot:
                self._responses.release()
