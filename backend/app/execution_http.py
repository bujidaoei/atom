"""Mountable execution-only ASGI boundary; explicit dependencies, no startup IO."""
import asyncio
from dataclasses import asdict
import json
import logging

from .artifacts import ArtifactError, ArtifactStore
from .execution import ExecutionCoordinator, ExecutionError
from .revisions import RevisionError
from .sandbox.client import BrokerClientError
from .sandbox.grants import CompletionGrantCodec, GrantError
from .snapshots import SnapshotError

_LOG = logging.getLogger(__name__)


class _Rejected(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate_key')
        value[key] = item
    return value


class ExecutionAPI:
    def __init__(self, coordinator: ExecutionCoordinator, store: ArtifactStore, codec: CompletionGrantCodec):
        if not isinstance(codec, CompletionGrantCodec):
            raise ExecutionError('invalid_completion_configuration')
        self.coordinator, self.store, self.codec = coordinator, store, codec

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            raise RuntimeError('execution_http_only')
        try:
            result = await self._handle(scope, receive)
            status, value = 200, result
        except _Rejected as error:
            status, value = error.status, {'error':error.code}
        except GrantError:
            status, value = 403, {'error':'invalid_execution_capability'}
        except RevisionError as error:
            status = 403 if error.code == 'revision_not_found' else 409 if error.code == 'revision_conflict' else 503
            value = {'error':'execution_scope_conflict' if status in (403,409) else 'execution_unavailable'}
        except (ArtifactError, SnapshotError, BrokerClientError, ExecutionError):
            status, value = 503, {'error':'execution_unavailable'}
        except Exception as error:
            _LOG.error('execution_request_failed', extra={'exception_type':type(error).__name__})
            status, value = 500, {'error':'execution_unavailable'}
        payload = json.dumps(value, separators=(',',':')).encode()
        async with asyncio.timeout(5):
            await send({'type':'http.response.start','status':status,'headers':[
                (b'content-type',b'application/json'),(b'cache-control',b'no-store'),
                (b'content-length',str(len(payload)).encode())]})
            await send({'type':'http.response.body','body':payload})

    async def _handle(self, scope, receive):
        path = scope['path'].removeprefix(scope.get('root_path',''))
        if path not in ('/v1/executions/complete','/v1/executions/cancel','/v1/executions/partial'):
            raise _Rejected(404,'not_found')
        if scope['method'] != 'POST':
            raise _Rejected(405,'method_not_allowed')
        headers = scope.get('headers',[])
        authorization = [v for k,v in headers if k.lower() == b'authorization']
        if len(authorization) != 1 or not authorization[0].startswith(b'Bearer '):
            raise _Rejected(401,'unauthorized')
        try:
            token = authorization[0][7:].decode('ascii')
        except UnicodeDecodeError:
            raise _Rejected(403,'invalid_execution_capability') from None
        grant = self.codec.verify(token)
        if scope.get('query_string'):
            raise _Rejected(400,'invalid_request')
        if any(k.lower() == b'content-encoding' for k,v in headers):
            raise _Rejected(415,'unsupported_encoding')
        partial = path.endswith('/partial')
        if partial and [v.lower() for k,v in headers if k.lower() == b'content-type'] != [b'application/json']:
            raise _Rejected(415,'unsupported_media_type')
        body = bytearray()
        try:
            async with asyncio.timeout(5):
                while True:
                    message = await receive()
                    chunk = message.get('body', b'')
                    if message['type'] != 'http.request' or not isinstance(chunk, bytes):
                        raise _Rejected(400,'body_not_allowed')
                    if (not partial and chunk) or len(body) + len(chunk) > 128:
                        raise _Rejected(400,'invalid_request')
                    body.extend(chunk)
                    if not message.get('more_body',False):
                        break
        except TimeoutError:
            raise _Rejected(408,'request_timeout') from None
        if partial:
            try:
                value = json.loads(body, object_pairs_hook=_unique_object)
            except (UnicodeDecodeError, ValueError):
                raise _Rejected(400,'invalid_request') from None
            if not isinstance(value, dict) or set(value) != {'outcome'} or value['outcome'] not in ('cancelled','timed_out'):
                raise _Rejected(400,'invalid_request')
        grant = self.codec.verify(token)
        await asyncio.to_thread(self.coordinator.repository.authorize_capability, grant.org, grant.attempt,
            grant_id=grant.jti,project_id=grant.project,run_id=grant.run,generation=grant.fence,
            base_revision=grant.base_revision,issued_at=grant.iat,deadline=grant.exp)
        if path.endswith('/complete'):
            result = await self.coordinator.complete(grant.org,grant.attempt,self.store)
        elif partial:
            try:
                result = await self.coordinator.checkpoint_incomplete(grant.org,grant.attempt,
                                                                       self.store,value['outcome'])
            except ExecutionError as error:
                if str(error) == 'execution_outcome_conflict':
                    raise _Rejected(409,'execution_scope_conflict') from None
                raise
        else:
            result = await self.coordinator.cancel(grant.org,grant.attempt)
        if result.state != 'closed' or result.termination_state != 'confirmed':
            raise ExecutionError('execution_unconfirmed')
        return asdict(result)
