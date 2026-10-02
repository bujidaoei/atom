"""Private, single-owner verifier process. Launch with ``uvicorn --factory``."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import hmac
import json
import logging
import os
from pathlib import Path
import re
import secrets

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.requests import ClientDisconnect

from .artifacts import ArtifactError, configured_artifact_store
from .storage_config import ObjectStorageSettings
from .bounded_operations import BoundedOperations, OwnedJSONResponse
from .migrations import MigrationError, verify
from .sandbox.daemon_lease import DaemonLeaseError
from .verification_repository import VerificationError
from .verifier_authority import VerifierAuthority
from .verifier_coordinator import VerifierCoordinator
from .verifier_supervisor import SupervisorError, VerifierSupervisor


_LOG = logging.getLogger(__name__)
_IDENTIFIER = re.compile(r'[A-Za-z0-9_.-]{1,128}\Z')
_IMAGE = re.compile(r'sha256:[0-9a-f]{64}\Z')


class VerifierStartupError(RuntimeError):
    pass


@dataclass(frozen=True)
class VerifierProcessConfig:
    database: Path
    artifacts: Path
    image: str
    seccomp: Path
    verifier_id: str
    control_token: str = field(repr=False)
    storage: ObjectStorageSettings = field(default_factory=lambda: ObjectStorageSettings(_env_file=None), repr=False)

    def __post_init__(self):
        if (not all(isinstance(path, Path) and path.is_absolute()
                    for path in (self.database, self.artifacts, self.seccomp))
                or type(self.image) is not str or _IMAGE.fullmatch(self.image) is None
                or type(self.verifier_id) is not str
                or _IDENTIFIER.fullmatch(self.verifier_id) is None
                or type(self.control_token) is not str
                or not 32 <= len(self.control_token) <= 256
                or not self.control_token.isascii()
                or any(ord(character) < 33 or ord(character) > 126
                       for character in self.control_token)):
            raise VerifierStartupError('verifier_configuration_invalid')

    @classmethod
    def from_environment(cls):
        names = ('ATOM_VERIFIER_DB_PATH', 'ATOM_VERIFIER_ARTIFACT_DIR',
                 'ATOM_VERIFIER_IMAGE', 'ATOM_VERIFIER_SECCOMP_PATH',
                 'ATOM_VERIFIER_ID', 'ATOM_VERIFIER_CONTROL_TOKEN')
        try:
            database, artifacts, image, seccomp, verifier_id, token = (
                os.environ[name] for name in names)
        except KeyError:
            raise VerifierStartupError('verifier_configuration_missing') from None
        return cls(Path(database), Path(artifacts), image, Path(seccomp),
                   verifier_id, token)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_key')
        result[key] = value
    return result


def _nonfinite(_value):
    raise ValueError('nonfinite_number')


def _error(code: str, status: int):
    return JSONResponse({'error':code}, status_code=status,
                        headers={'cache-control':'no-store'})


def create_app(config: VerifierProcessConfig | None = None) -> FastAPI:
    if config is None:
        config = VerifierProcessConfig.from_environment()
    if type(config) is not VerifierProcessConfig:
        raise VerifierStartupError('verifier_configuration_invalid')
    try:
        if verify(config.database) not in (13, 14, 15, 16, 17):
            raise VerifierStartupError('verifier_schema_required')
        store = configured_artifact_store(config.storage, config.artifacts)
        authority = VerifierAuthority(config.database)
        supervisor = VerifierSupervisor(image=config.image, seccomp_path=config.seccomp,
                                        verifier_id=config.verifier_id)
    except (MigrationError, ArtifactError, VerificationError, SupervisorError):
        raise VerifierStartupError('verifier_startup_unavailable') from None
    coordinator = VerifierCoordinator(supervisor)
    operations = BoundedOperations(capacity=1)

    @asynccontextmanager
    async def lifespan(_app):
        try:
            await asyncio.to_thread(coordinator.start)
        except (SupervisorError, DaemonLeaseError):
            raise VerifierStartupError('verifier_owner_unavailable') from None
        operations.start()
        try:
            yield
        finally:
            await operations.drain(timeout=60)
            await asyncio.to_thread(coordinator.close)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.get('/health')
    async def health():
        try:
            await asyncio.to_thread(coordinator._require_lease)
            if verify(config.database) not in (13, 14, 15, 16, 17):
                raise VerifierStartupError('verifier_schema_required')
        except (SupervisorError, MigrationError, VerifierStartupError):
            return _error('verifier_unavailable', 503)
        return JSONResponse({'ok':True}, headers={'cache-control':'no-store'})

    def run(owner: str, request_id: str):
        assignment = authority.dispatch_current(
            owner=owner, request_id=request_id, route_id=secrets.token_hex(16),
            verifier_id=supervisor.verifier_id,
            environment_digest=supervisor.environment_digest)
        return coordinator.verify_and_register(assignment=assignment, store=store,
                                               authority=authority, budget_seconds=30)

    def finish_abandoned(task, token):
        try:
            error = task.exception()
            if error is not None:
                _LOG.warning('verifier_abandoned_request_failed',
                             extra={'exception_type':type(error).__name__})
        except asyncio.CancelledError:
            _LOG.warning('verifier_abandoned_request_cancelled')
        finally:
            operations.release(token)

    @app.post('/v1/verify')
    async def verify_request(request: Request):
        headers = request.scope['headers']
        authorization = [value for key, value in headers if key.lower() == b'authorization']
        expected = b'Bearer ' + config.control_token.encode('ascii')
        if len(authorization) != 1 or not hmac.compare_digest(authorization[0], expected):
            return _error('unauthorized', 401)
        if request.scope.get('query_string'):
            return _error('invalid_request', 400)
        if ([value.lower() for key, value in headers if key.lower() == b'content-type']
                != [b'application/json']
                or any(key.lower() == b'content-encoding' for key, _ in headers)):
            return _error('unsupported_content_type', 415)
        body = bytearray()
        try:
            async with asyncio.timeout(5):
                async for chunk in request.stream():
                    if len(body) + len(chunk) > 512:
                        return _error('request_too_large', 413)
                    body.extend(chunk)
        except (TimeoutError, ClientDisconnect):
            return _error('invalid_request', 400)
        try:
            data = json.loads(body.decode('utf-8'), object_pairs_hook=_unique,
                              parse_constant=_nonfinite)
        except (ValueError, UnicodeError, RecursionError):
            return _error('invalid_request', 400)
        if (type(data) is not dict or set(data) != {'owner', 'requestId'}
                or any(type(data[key]) is not str or _IDENTIFIER.fullmatch(data[key]) is None
                       for key in ('owner', 'requestId'))):
            return _error('invalid_request', 400)
        token = operations.acquire()
        if token is None:
            return _error('verifier_busy', 503)
        task = asyncio.create_task(asyncio.to_thread(run, data['owner'], data['requestId']))
        try:
            result = await asyncio.shield(task)
            response = {'requestId':result.request_id, 'revisionId':result.revision_id,
                        'outcome':result.outcome, 'total':result.total,
                        'passed':result.passed}
            return OwnedJSONResponse(response, operations, token,
                                     headers={'cache-control':'no-store'})
        except asyncio.CancelledError:
            task.add_done_callback(lambda finished: finish_abandoned(finished, token))
            raise
        except VerificationError as error:
            status = (404 if str(error) == 'verification_not_found' else
                      409 if str(error) in {
                          'verifier_already_dispatched', 'verification_expired',
                          'verification_stale_contract', 'verification_stale_artifact',
                          'verification_stale_evidence'} else 503)
            return OwnedJSONResponse({'error':str(error)}, operations, token,
                                     status_code=status,
                                     headers={'cache-control':'no-store'})
        except (SupervisorError, ArtifactError):
            return OwnedJSONResponse({'error':'verifier_unavailable'}, operations,
                                     token, status_code=503,
                                     headers={'cache-control':'no-store'})
        except Exception as error:
            _LOG.error('verifier_request_failed', extra={'exception_type':type(error).__name__})
            return OwnedJSONResponse({'error':'verifier_unavailable'}, operations,
                                     token, status_code=503,
                                     headers={'cache-control':'no-store'})

    return app
