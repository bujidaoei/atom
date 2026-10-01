"""Standalone public content ASGI service; no console credentials or API proxy."""
import mimetypes

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


class ContentService:
    def __init__(self, repository, store, hosts):
        self.repository, self.store, self.hosts = repository, store, hosts

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

    async def __call__(self,scope,receive,send):
        if scope['type']!='http':
            raise RuntimeError('content_http_only')
        method = scope.get('method')
        try:
            binding = self.hosts.binding(scope.get('headers',[]))
            if method not in ('GET','HEAD'):
                response = Response(status_code=405,headers={**HEADERS,'Allow':'GET, HEAD'})
            else:
                # Browser navigation metadata is a fallback hint, never auth.
                navigation = any(k.lower()==b'sec-fetch-mode' and v==b'navigate' for k,v in scope['headers'])
                response = await run_in_threadpool(self._read,binding,scope.get('path','/'),navigation)
        except ContentHostError:
            response = Response(status_code=404,headers=HEADERS)
        except VerificationError as error:
            code = 404 if str(error) in ('content_not_found','release_not_found') else 503
            response = Response(status_code=code,headers=HEADERS)
        except (ArtifactError,SnapshotError,OSError):
            response = Response(status_code=503,headers=HEADERS)
        if method=='HEAD':
            response.body=b''
        await response(scope,receive,send)
