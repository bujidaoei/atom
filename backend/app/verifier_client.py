"""Trusted console-to-verifier transport; never exposed to generated runtimes."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import math
import re
from urllib.parse import urlsplit

import httpx


_ID = re.compile(r'[A-Za-z0-9_.-]{1,128}\Z')
_ERRORS = {
    (404, 'verification_not_found'),
    (409, 'verifier_already_dispatched'),
    (409, 'verification_expired'),
    (409, 'verification_stale_contract'),
    (409, 'verification_stale_artifact'),
    (409, 'verification_stale_evidence'),
    (503, 'verifier_busy'),
}


class VerifierClientError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class VerifierObservation:
    request_id: str
    revision_id: str
    outcome: str
    total: int
    passed: int


def _origin(value: str) -> str:
    try:
        if (type(value) is not str or not value.isascii()
                or any(ord(char) < 33 or ord(char) > 126 or char in '\\%?#'
                       for char in value)):
            raise ValueError
        parts = urlsplit(value)
        allowed_loopback = parts.hostname in ('127.0.0.1', '::1')
        allowed_private_service = parts.netloc == 'atom-verifier:8765'
        if (parts.scheme != 'http' or not (allowed_loopback or allowed_private_service)
                or parts.username is not None or parts.password is not None
                or parts.path not in ('', '/') or parts.query or parts.fragment
                or parts.port is None or not 1 <= parts.port <= 65535
                or parts.netloc.endswith(':')):
            raise ValueError
        return value.rstrip('/')
    except (ValueError, TypeError):
        raise VerifierClientError('invalid_verifier_client_configuration') from None


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_key')
        result[key] = value
    return result


def _nonfinite(_value):
    raise ValueError('nonfinite_number')


def _document(payload: bytes):
    try:
        value = json.loads(payload.decode('utf-8'), object_pairs_hook=_unique,
                           parse_constant=_nonfinite)
        if type(value) is not dict:
            raise ValueError
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise VerifierClientError('invalid_verifier_response') from None


class VerifierClient:
    def __init__(self, origin: str, control_token: str, *, timeout: float = 45):
        self._origin = _origin(origin)
        if (type(control_token) is not str or not 32 <= len(control_token) <= 256
                or not control_token.isascii()
                or any(ord(char) < 33 or ord(char) > 126 for char in control_token)
                or isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout) or not 1 <= timeout <= 60):
            raise VerifierClientError('invalid_verifier_client_configuration')
        self._token = control_token
        self._timeout = timeout
        self._http = httpx.AsyncClient(base_url=self._origin, trust_env=False,
            follow_redirects=False, timeout=timeout,
            limits=httpx.Limits(max_connections=2, max_keepalive_connections=1))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        await self.close()

    async def close(self):
        await self._http.aclose()

    async def require_ready(self):
        if self._http.is_closed:
            raise VerifierClientError('verifier_client_closed')
        try:
            async with asyncio.timeout(min(self._timeout, 5)):
                async with self._http.stream('GET', '/health',
                    headers={'accept-encoding':'identity'}) as response:
                    if (response.status_code != 200
                            or [value.lower() for value in response.headers.get_list('content-type')]
                               != ['application/json']
                            or response.headers.get_list('content-encoding')):
                        raise VerifierClientError('verifier_unavailable')
                    body = bytearray()
                    async for chunk in response.aiter_raw():
                        if len(body) + len(chunk) > 64:
                            raise VerifierClientError('verifier_unavailable')
                        body.extend(chunk)
                    try:
                        if _document(bytes(body)) != {'ok':True}:
                            raise VerifierClientError('verifier_unavailable')
                    except VerifierClientError:
                        raise VerifierClientError('verifier_unavailable') from None
        except (httpx.HTTPError, TimeoutError, OSError):
            raise VerifierClientError('verifier_unavailable') from None

    async def verify(self, *, owner: str, request_id: str) -> VerifierObservation:
        if (type(owner) is not str or _ID.fullmatch(owner) is None
                or type(request_id) is not str or _ID.fullmatch(request_id) is None):
            raise VerifierClientError('invalid_verifier_request')
        if self._http.is_closed:
            raise VerifierClientError('verifier_client_closed')
        body = json.dumps({'owner':owner, 'requestId':request_id},
                          separators=(',', ':')).encode('utf-8')
        try:
            async with asyncio.timeout(self._timeout):
                async with self._http.stream('POST', '/v1/verify', content=body,
                    headers={'authorization':'Bearer ' + self._token,
                             'content-type':'application/json',
                             'accept-encoding':'identity'}) as response:
                    if ([value.lower() for value in response.headers.get_list('content-type')]
                            != ['application/json']
                            or response.headers.get_list('content-encoding')):
                        raise VerifierClientError('invalid_verifier_response')
                    payload = bytearray()
                    async for chunk in response.aiter_raw():
                        if len(payload) + len(chunk) > 512:
                            raise VerifierClientError('invalid_verifier_response')
                        payload.extend(chunk)
                    data = _document(bytes(payload))
                    if response.status_code != 200:
                        if (set(data) == {'error'} and type(data['error']) is str
                                and (response.status_code, data['error']) in _ERRORS):
                            raise VerifierClientError(data['error'])
                        raise VerifierClientError('verifier_http_error')
                    if (set(data) != {'requestId','revisionId','outcome','total','passed'}
                            or data['requestId'] != request_id
                            or type(data['revisionId']) is not str
                            or _ID.fullmatch(data['revisionId']) is None
                            or data['outcome'] not in ('passed','failed')
                            or type(data['total']) is not int or not 1 <= data['total'] <= 128
                            or type(data['passed']) is not int
                            or not 0 <= data['passed'] <= data['total']
                            or (data['outcome'] == 'passed') !=
                               (data['passed'] == data['total'])):
                        raise VerifierClientError('invalid_verifier_response')
                    return VerifierObservation(request_id, data['revisionId'],
                                               data['outcome'], data['total'], data['passed'])
        except (httpx.HTTPError, TimeoutError, OSError):
            # The worker may have registered after transport loss. A caller must
            # inspect the durable ledger; a second dispatch cannot be retried.
            raise VerifierClientError('verifier_outcome_unknown') from None
