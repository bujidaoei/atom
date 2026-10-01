"""Trusted administrative transport; never pass this client to agent runtime."""
import asyncio
from dataclasses import dataclass
import hashlib
import io
import json
import re
import time
from urllib.parse import urlsplit

import httpx

from .checkpoints import CheckpointExport
from .grants import Grant, GrantCodec, GrantError
from ..revisions import Receipt
from ..snapshots import MAX_ARCHIVE_BYTES, SnapshotError, verify_snapshot

_ID = re.compile(r'[0-9a-f]{32}\Z')
_HASH = re.compile(r'[0-9a-f]{64}\Z')


class BrokerClientError(RuntimeError):
    def __init__(self, code, *, status=None):
        self.code, self.status = code, status
        super().__init__(code)


@dataclass(frozen=True)
class Provisioned:
    attempt_id: str
    state: str
    deadline: int


@dataclass(frozen=True)
class CheckpointAcknowledgement:
    attempt_id: str
    version: int
    revision: str


@dataclass(frozen=True)
class CheckpointState:
    attempt_id: str
    state: str
    version: int
    revision: str | None


def _origin(value):
    try:
        if not isinstance(value, str) or any(ord(c) < 33 or ord(c) > 126 or c == '\\' for c in value):
            raise ValueError
        url = urlsplit(value)
        if (url.scheme not in ('http','https') or not url.hostname or url.username is not None
                or url.password is not None or url.query or url.fragment or '?' in value or '#' in value
                or url.path not in ('','/') or url.port == 0 or '%' in url.netloc or url.netloc.endswith(':')
                or (url.scheme == 'http' and url.hostname not in ('127.0.0.1','::1'))):
            raise ValueError
        return value.rstrip('/')
    except (ValueError, TypeError):
        raise BrokerClientError('invalid_broker_client_configuration') from None


def _json(payload):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError
            value[key] = item
        return value
    def nonfinite(_value):
        raise ValueError
    try:
        value = json.loads(payload.decode('utf-8'), object_pairs_hook=unique, parse_constant=nonfinite)
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (ValueError, TypeError, RecursionError):
        raise BrokerClientError('invalid_broker_response') from None


def _service_error(payload):
    try:
        value = _json(payload)
    except BrokerClientError:
        return None
    if set(value) != {'error'}:
        return None
    code = value['error']
    return code if code in {'broker_busy','broker_not_ready','registry_unavailable',
                            'lifecycle_unavailable'} else None


def _identifier(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise BrokerClientError('invalid_broker_request')


def _snapshot(payload, revision):
    if not isinstance(payload, bytes) or len(payload) > MAX_ARCHIVE_BYTES:
        raise BrokerClientError('invalid_checkpoint')
    try:
        verified = verify_snapshot(io.BytesIO(payload))
    except SnapshotError:
        raise BrokerClientError('invalid_checkpoint') from None
    if verified.revision != revision:
        raise BrokerClientError('invalid_checkpoint')


class AdminTransport:
    def __init__(self, origin: str, admin_token: str, *, timeout: float = 45):
        self._origin = _origin(origin)
        if (not isinstance(admin_token, str) or not 32 <= len(admin_token) <= 128
                or any(not 33 <= ord(c) <= 126 for c in admin_token)
                or isinstance(timeout, bool)
                or not isinstance(timeout, (int,float)) or not 0 < timeout <= 60):
            raise BrokerClientError('invalid_broker_client_configuration')
        self._admin, self._timeout = admin_token, timeout
        try:
            self._http = httpx.AsyncClient(base_url=self._origin, follow_redirects=False,
                trust_env=False, timeout=timeout, limits=httpx.Limits(max_connections=4,max_keepalive_connections=2))
        except (ValueError, httpx.InvalidURL):
            raise BrokerClientError('invalid_broker_client_configuration') from None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        await self._http.aclose()

    async def _request(self, route, payload, *, headers=None, expected=200,
                       media='application/json', limit=16384, method='POST'):
        if self._http.is_closed:
            raise BrokerClientError('broker_client_closed')
        outgoing = {'authorization':'Bearer '+self._admin, 'accept-encoding':'identity', **(headers or {})}
        try:
            async with asyncio.timeout(self._timeout):
                async with self._http.stream(method,route,content=payload,headers=outgoing) as response:
                    if response.status_code != expected:
                        # Only a small, exact broker-owned error envelope may be
                        # classified. Arbitrary responses stay non-retryable.
                        if (response.status_code == 503
                                and response.headers.get_list('content-type') == ['application/json']
                                and not response.headers.get_list('content-encoding')):
                            data = bytearray()
                            async for chunk in response.aiter_raw():
                                if len(data) + len(chunk) > 128:
                                    break
                                data.extend(chunk)
                            else:
                                code = _service_error(bytes(data))
                                if code:
                                    raise BrokerClientError(code,status=503)
                        raise BrokerClientError('broker_http_error',status=response.status_code)
                    if ([v.lower() for v in response.headers.get_list('content-type')] != [media]
                            or response.headers.get_list('content-encoding')):
                        raise BrokerClientError('invalid_broker_response')
                    data = bytearray()
                    async for chunk in response.aiter_raw():
                        if len(data) + len(chunk) > limit:
                            raise BrokerClientError('invalid_broker_response')
                        data.extend(chunk)
                    return response.headers, bytes(data)
        except (httpx.HTTPError, TimeoutError, OSError):
            raise BrokerClientError('broker_outcome_unknown') from None

    async def _json_request(self, route, body, *, expected=200):
        _, payload = await self._request(route,json.dumps(body,separators=(',',':')).encode(),
            headers={'content-type':'application/json'},expected=expected)
        return _json(payload)

class BrokerClient(AdminTransport):
    def __init__(self, origin: str, admin_token: str, codec: GrantCodec, *, timeout: float = 45):
        if not isinstance(codec, GrantCodec):
            raise BrokerClientError('invalid_broker_client_configuration')
        super().__init__(origin,admin_token,timeout=timeout)
        self._codec = codec

    def _token(self, grant):
        try:
            return self._codec.issue(grant)
        except (GrantError, TypeError, AttributeError):
            raise BrokerClientError('invalid_broker_request') from None

    def runtime_token(self, grant: Grant) -> str:
        """Issue scoped bearer authority for a trusted coordinator's ready lease."""
        return self._token(grant)

    async def _pre_dispatch_busy(self, operation, grant: Grant):
        """Repeat only an explicit broker busy rejection, never an unknown effect."""
        end = time.monotonic() + min(20.0, max(0.0, grant.exp - time.time() - 5.0))
        delay = 0.15
        while True:
            try:
                return await operation()
            except BrokerClientError as error:
                if error.code != 'broker_busy' or time.monotonic() + delay >= end:
                    raise
                await asyncio.sleep(delay)
                delay = min(delay * 2, 1.0)

    async def require_ready(self) -> None:
        try:
            async with asyncio.timeout(5):
                _, payload = await self._request('/ready', None, method='GET', limit=1024)
        except TimeoutError:
            raise BrokerClientError('broker_not_ready') from None
        value = _json(payload)
        if set(value) != {'alive','ready'} or value['alive'] is not True or value['ready'] is not True:
            raise BrokerClientError('broker_not_ready')

    @staticmethod
    def _provisioned(value, grant, states, expected_id=None):
        if (set(value) != {'attempt_id','state','deadline'} or not isinstance(value['attempt_id'],str)
                or not _ID.fullmatch(value['attempt_id']) or value['state'] not in states
                or type(value['deadline']) is not int or value['deadline'] != grant.exp
                or (expected_id is not None and value['attempt_id'] != expected_id)):
            raise BrokerClientError('invalid_broker_response')
        return Provisioned(**value)

    async def provision(self, grant: Grant) -> Provisioned:
        result = await self._pre_dispatch_busy(
            lambda: self._json_request('/v1/admin/provision',{'grant':self._token(grant)},expected=202), grant)
        return self._provisioned(result,grant,('provisioning','ready'))

    async def seed(self, grant: Grant, attempt_id: str, payload: bytes) -> Provisioned:
        _identifier(attempt_id)
        token = self._token(grant)
        _snapshot(payload,grant.base_revision)
        _, result = await self._pre_dispatch_busy(lambda: self._request(
            '/v1/admin/seed',payload,headers={
                'content-type':'application/octet-stream','x-atom-grant':token}), grant)
        return self._provisioned(_json(result),grant,('ready',),attempt_id)

    async def export(self, grant: Grant, attempt_id: str) -> CheckpointExport:
        _identifier(attempt_id)
        headers, payload = await self._request('/v1/admin/checkpoints/export',
            json.dumps({'attempt_id':attempt_id}).encode(),headers={
                'content-type':'application/json','x-atom-grant':self._token(grant)},
            media='application/octet-stream',limit=MAX_ARCHIVE_BYTES)
        def field(name, pattern):
            values = headers.get_list(name)
            if len(values) != 1 or not pattern.fullmatch(values[0]):
                raise BrokerClientError('invalid_broker_response')
            return values[0]
        identity = field('x-atom-attempt',_ID)
        version = int(field('x-atom-export-version',re.compile(r'[1-9][0-9]{0,18}\Z')))
        revision = field('x-atom-revision',_HASH)
        digest = field('x-atom-artifact-key',_HASH)
        if identity != attempt_id or version > 9223372036854775807 or digest != hashlib.sha256(payload).hexdigest():
            raise BrokerClientError('invalid_broker_response')
        _snapshot(payload,revision)
        return CheckpointExport(identity,version,revision,payload)

    async def checkpoint_status(self, grant: Grant, attempt_id: str) -> CheckpointState:
        _identifier(attempt_id)
        _, raw = await self._request('/v1/admin/checkpoints/status',
            json.dumps({'attempt_id':attempt_id}).encode(), headers={
                'content-type':'application/json', 'x-atom-grant':self._token(grant)})
        value = _json(raw)
        if (set(value) != {'attempt_id','state','version','revision'} or value['attempt_id'] != attempt_id
                or value['state'] not in ('quiescing','checkpointed') or type(value['version']) is not int
                or not 1 <= value['version'] <= 9223372036854775807
                or (value['state'] == 'quiescing' and value['revision'] is not None)
                or (value['state'] == 'checkpointed' and
                    (not isinstance(value['revision'], str) or not _HASH.fullmatch(value['revision'])))):
            raise BrokerClientError('invalid_broker_response')
        return CheckpointState(value['attempt_id'],value['state'],value['version'],value['revision'])

    async def confirm(self, grant: Grant, exported: CheckpointExport, receipt: Receipt) -> CheckpointAcknowledgement:
        if not isinstance(exported,CheckpointExport) or not isinstance(receipt,Receipt):
            raise BrokerClientError('invalid_broker_request')
        _identifier(exported.attempt_id)
        token = self._token(grant)
        _snapshot(exported.payload,exported.revision)
        if (type(exported.attempt_version) is not int or not 1 <= exported.attempt_version < 9223372036854775807
                or receipt.attempt_id != grant.attempt or receipt.snapshot_revision != exported.revision
                or receipt.artifact_key != hashlib.sha256(exported.payload).hexdigest()):
            raise BrokerClientError('invalid_broker_request')
        _, raw = await self._request('/v1/admin/checkpoints/confirm',exported.payload,headers={
            'content-type':'application/octet-stream','x-atom-grant':token,'x-atom-attempt':exported.attempt_id,
            'x-atom-export-version':str(exported.attempt_version),'x-atom-registered-revision':receipt.snapshot_revision})
        value = _json(raw)
        if (set(value) != {'attempt_id','state','version','revision'} or value['attempt_id'] != exported.attempt_id
                or value['state'] != 'checkpointed' or type(value['version']) is not int
                or value['version'] != exported.attempt_version+1 or value['revision'] != exported.revision):
            raise BrokerClientError('invalid_broker_response')
        return CheckpointAcknowledgement(value['attempt_id'],value['version'],value['revision'])

    async def revoke(self, grant_id: str) -> str:
        if not isinstance(grant_id,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',grant_id):
            raise BrokerClientError('invalid_broker_request')
        value = await self._json_request('/v1/admin/revoke',{'grant_id':grant_id})
        if set(value) != {'revoked','state'} or value['revoked'] is not True or value['state'] not in ('terminated','not_admitted'):
            raise BrokerClientError('invalid_broker_response')
        return value['state']
