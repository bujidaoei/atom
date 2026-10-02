"""Private administrative and grant-scoped sandbox HTTP boundaries."""
import asyncio
from contextlib import asynccontextmanager
import hmac
import hashlib
import json
import logging
import re

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from .config import BrokerConfig
from .docker_driver import DockerDriver, DriverError
from .daemon_lease import BrokerDaemonLease, DaemonLeaseError
from .grants import GrantCodec, GrantError
from .lifecycle import Lifecycle, LifecycleError
from .registry import Registry, RegistryError
from .seeding import MAX_SEED_BYTES
from .file_helper import validate
from .checkpoints import CheckpointExport
from ..snapshots import MAX_ARCHIVE_BYTES
from ..audit_archive import ArchiveError, MAX_ARCHIVE_BYTES as MAX_AUDIT_ARCHIVE_BYTES, decode_archive

_LOG = logging.getLogger("atom.sandbox")
_CHECKPOINT_SEND_SECONDS = 10


class _SnapshotResponse(Response):
    """Own the transfer slot until bounded ASGI delivery completes or fails."""
    def __init__(self, content, *, lock, headers, media_type="application/octet-stream"):
        self._lock = lock
        super().__init__(content, media_type=media_type, headers=headers)

    async def __call__(self, scope, receive, send):
        try:
            async with asyncio.timeout(_CHECKPOINT_SEND_SECONDS):
                await super().__call__(scope, receive, send)
        finally:
            self._lock.release()


class ServiceError(Exception):
    def __init__(self, status: int, code: str):
        self.status, self.code = status, code


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError


async def _read_body(request: Request, media_type: str, limit: int) -> bytes:
    if ([value.lower() for value in request.headers.getlist("content-type")] != [media_type]
            or request.headers.getlist("content-encoding")):
        raise ServiceError(415, "unsupported_content_type")
    data = bytearray()
    try:
        async with asyncio.timeout(5):
            async for chunk in request.stream():
                if len(data) + len(chunk) > limit:
                    raise ServiceError(413, "request_too_large")
                data.extend(chunk)
        return bytes(data)
    except TimeoutError:
        raise ServiceError(408, "request_timeout") from None
    except ClientDisconnect:
        raise ServiceError(400, "invalid_request") from None


def _json(data: bytes):
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_nonfinite)
    except (ValueError, TypeError, RecursionError):
        raise ServiceError(400, "invalid_request") from None


async def _body(request: Request, field: str) -> str:
    value = _json(await _read_body(request, "application/json", 12288))
    try:
        if not isinstance(value, dict) or set(value) != {field} or not isinstance(value[field], str):
            raise ValueError
        return value[field]
    except (ValueError, TypeError, RecursionError):
        raise ServiceError(400, "invalid_request") from None


def create_app(config: BrokerConfig | None = None) -> FastAPI:
    config = config or BrokerConfig.from_env()
    codec = GrantCodec(config.grant_key.encode("ascii"), max_lifetime=7200)

    @asynccontextmanager
    async def lifespan(app):
        registry = Registry(config.registry_path)
        daemon_lease = BrokerDaemonLease(registry.broker_id, config.image)
        lifecycle = None
        app.state.lifecycle = None
        app.state.transfer_lock = asyncio.Lock()
        app.state.maintenance_ok = False
        stop = asyncio.Event()

        async def reconcile():
            nonlocal lifecycle
            try:
                if lifecycle is None:
                    await run_in_threadpool(daemon_lease.acquire)
                    try:
                        lifecycle = Lifecycle(registry, DockerDriver(registry.broker_id, config.image),
                                              batch_size=config.batch_size,
                                              lease_alive=lambda: daemon_lease.alive)
                    except Exception:
                        await run_in_threadpool(daemon_lease.close)
                        raise
                    app.state.lifecycle = lifecycle
                if not daemon_lease.alive:
                    app.state.maintenance_ok = False
                    _LOG.error("broker_identity_lease_lost")
                    return
                await run_in_threadpool(lifecycle.sweep)
                # Cleanup old owned resources even if the configured next image
                # is unavailable; readiness still requires that image to exist.
                await run_in_threadpool(lifecycle.driver.validate_environment)
                app.state.maintenance_ok = True
            except (RegistryError, DriverError, LifecycleError, DaemonLeaseError):
                app.state.maintenance_ok = False
                _LOG.warning("broker_reconciliation_failed")
            except Exception:
                app.state.maintenance_ok = False
                _LOG.error("broker_maintenance_failed")

        async def periodic():
            while not stop.is_set():
                try:
                    await asyncio.wait_for(stop.wait(), timeout=config.sweep_seconds)
                except TimeoutError:
                    await reconcile()

        task = None
        try:
            await reconcile()
            task = asyncio.create_task(periodic(), name="broker-reconciliation")
            yield
        finally:
            app.state.maintenance_ok = False
            stop.set()
            if task is not None:
                await task
            if lifecycle is not None:
                try:
                    if daemon_lease.alive:
                        await run_in_threadpool(lifecycle.close)
                    else:
                        await run_in_threadpool(lifecycle.abandon_after_lease_loss)
                except (RegistryError, DriverError, LifecycleError):
                    _LOG.error("broker_shutdown_unconfirmed")
                    raise ServiceError(503, "shutdown_unconfirmed") from None
                finally:
                    await run_in_threadpool(daemon_lease.close)
            else:
                await run_in_threadpool(daemon_lease.close)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    def authenticate(request):
        values = request.headers.getlist("authorization")
        expected = ("Bearer " + config.admin_token).encode("ascii")
        if len(values) != 1 or not hmac.compare_digest(values[0].encode("latin-1"), expected):
            raise ServiceError(401, "unauthorized")

    async def ready():
        lifecycle = getattr(app.state, "lifecycle", None)
        if lifecycle is None or not app.state.maintenance_ok:
            return False
        status = await run_in_threadpool(lifecycle.ready_after_control)
        return status and app.state.maintenance_ok

    def signed_header(request, header="authorization"):
        values = request.headers.getlist(header)
        if len(values) != 1:
            raise ServiceError(401, "unauthorized")
        token = values[0]
        if header == "authorization":
            if not token.startswith("Bearer "):
                raise ServiceError(401, "unauthorized")
            token = token[7:]
        try:
            return codec.verify(token)
        except GrantError:
            raise ServiceError(403, "invalid_grant") from None

    async def acquire_transfer():
        lifecycle = getattr(app.state, "lifecycle", None)
        if lifecycle is None or not app.state.maintenance_ok:
            raise ServiceError(503, "broker_not_ready")
        lock = app.state.transfer_lock
        # There is no await between observing and acquiring an unlocked lock;
        # all intake runs on the single service event loop.
        if lock.locked():
            raise ServiceError(503, "broker_busy")
        await lock.acquire()
        return lifecycle, lock

    @asynccontextmanager
    async def transfer():
        lifecycle, lock = await acquire_transfer()
        try:
            yield lifecycle
        finally:
            lock.release()

    async def control(function, *args, **kwargs):
        try:
            return await run_in_threadpool(function, *args, **kwargs)
        except RegistryError as error:
            status = 503 if error.code == "registry_unavailable" else 409
            raise ServiceError(status, "registry_unavailable" if status == 503 else "ownership_conflict") from None
        except LifecycleError as error:
            if error.code == "invalid_checkpoint_acknowledgement":
                raise ServiceError(400, "invalid_checkpoint") from None
            if error.code == "broker_busy":
                # Lifecycle's control lock rejected before the operation ran.
                raise ServiceError(503, "broker_busy") from None
            _LOG.warning("broker_lifecycle_rejected code=%s", error.code)
            raise ServiceError(503, "lifecycle_unavailable") from None
        except DriverError as error:
            _LOG.warning("broker_driver_rejected code=%s", error.code)
            raise ServiceError(503, "lifecycle_unavailable") from None

    @app.exception_handler(ServiceError)
    async def handle(_request, error):
        return JSONResponse({"error": error.code}, status_code=error.status)

    @app.get("/health")
    @app.get("/ready")
    async def health(request: Request):
        authenticate(request)
        status = await ready()
        return JSONResponse({"alive": True, "ready": status}, status_code=503 if request.url.path == "/ready" and not status else 200)

    @app.post("/v1/admin/provision", status_code=202)
    async def provision(request: Request):
        authenticate(request)
        token = await _body(request, "grant")
        try:
            grant = codec.verify(token)
        except GrantError:
            raise ServiceError(403, "invalid_grant") from None
        # A sweep temporarily clears lifecycle.ready while holding its control
        # lock. Wait behind that lock; provision rechecks readiness afterwards.
        if getattr(app.state, "lifecycle", None) is None or not app.state.maintenance_ok:
            raise ServiceError(503, "broker_not_ready")
        attempt = await control(app.state.lifecycle.provision, grant)
        return {"attempt_id": attempt.id, "state": attempt.state, "deadline": attempt.deadline}

    @app.post("/v1/admin/revoke")
    async def revoke(request: Request):
        authenticate(request)
        grant_id = await _body(request, "grant_id")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", grant_id):
            raise ServiceError(400, "invalid_request")
        lifecycle = getattr(app.state, "lifecycle", None)
        if lifecycle is None:
            raise ServiceError(503, "broker_not_ready")
        attempt = await control(lifecycle.revoke, grant_id)
        return {"revoked": True, "state": attempt.state if attempt else "not_admitted"}

    @app.post("/v1/admin/seed")
    async def seed(request: Request):
        authenticate(request)
        grant = signed_header(request, "x-atom-grant")
        async with transfer() as lifecycle:
            await control(lifecycle.registry.authorize_provisioning, grant)
            payload = await _read_body(request, "application/octet-stream", MAX_SEED_BYTES)
            attempt = await control(lifecycle.seed, grant, payload)
            return JSONResponse({"attempt_id": attempt.id, "state": attempt.state, "deadline": attempt.deadline})

    @app.post("/v1/admin/audit/recover")
    async def recover_audit(request: Request):
        authenticate(request)
        digests = request.headers.getlist('x-atom-archive-sha256')
        if len(digests) != 1 or re.fullmatch(r'[0-9a-f]{64}', digests[0]) is None:
            raise ServiceError(400, 'invalid_archive_digest')
        lifecycle, lock = await acquire_transfer()
        try:
            payload = await _read_body(request, 'application/octet-stream', MAX_AUDIT_ARCHIVE_BYTES)
            try:
                decode_archive(payload, expected_sha256=digests[0])
            except ArchiveError:
                raise ServiceError(400, 'invalid_audit_archive') from None
            # Cancellation must not abandon the worker thread or release its admission slot early.
            operation = asyncio.create_task(control(lifecycle.verify_audit_archive,payload,expected_sha256=digests[0]))
            try:
                result = await asyncio.shield(operation)
            except asyncio.CancelledError:
                while not operation.done():
                    try:
                        await asyncio.shield(operation)
                    except asyncio.CancelledError:
                        continue
                    except Exception:
                        break
                if not operation.cancelled():
                    operation.exception()
                raise
            except ArchiveError:
                raise ServiceError(503, 'archive_recovery_unavailable') from None
            encoded = json.dumps(result,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('ascii')
            if len(encoded) > MAX_AUDIT_ARCHIVE_BYTES+2048:
                raise ServiceError(503, 'archive_recovery_unavailable')
            return _SnapshotResponse(encoded,lock=lock,headers={'cache-control':'no-store'},media_type='application/json')
        except BaseException:
            lock.release()
            raise

    @app.post("/v1/admin/checkpoints/status")
    async def checkpoint_status(request: Request):
        authenticate(request)
        grant = signed_header(request, "x-atom-grant")
        async with transfer() as lifecycle:
            attempt_id = await _body(request, "attempt_id")
            if not re.fullmatch(r"[0-9a-f]{32}", attempt_id):
                raise ServiceError(400, "invalid_request")
            attempt = await control(lifecycle.registry.checkpoint_status, grant)
            if attempt.id != attempt_id:
                raise ServiceError(409, "ownership_conflict")
            return {"attempt_id": attempt.id, "state": attempt.state, "version": attempt.version,
                    "revision": attempt.checkpoint_revision}

    @app.post("/v1/admin/checkpoints/export")
    async def export_checkpoint(request: Request):
        authenticate(request)
        grant = signed_header(request, "x-atom-grant")
        lifecycle, lock = await acquire_transfer()
        try:
            attempt_id = await _body(request, "attempt_id")
            if not re.fullmatch(r"[0-9a-f]{32}", attempt_id):
                raise ServiceError(400, "invalid_request")
            attempt = await control(lifecycle.registry.authorize_checkpoint, grant)
            if attempt.id != attempt_id:
                raise ServiceError(409, "ownership_conflict")
            exported = await control(lifecycle.export_checkpoint, grant)
            return _SnapshotResponse(exported.payload, lock=lock, headers={
                "cache-control": "no-store", "x-atom-attempt": exported.attempt_id,
                "x-atom-export-version": str(exported.attempt_version), "x-atom-revision": exported.revision,
                "x-atom-artifact-key": hashlib.sha256(exported.payload).hexdigest()})
        except BaseException:
            lock.release()
            raise

    @app.post("/v1/admin/checkpoints/confirm")
    async def confirm_checkpoint(request: Request):
        authenticate(request)
        grant = signed_header(request, "x-atom-grant")
        def field(name, pattern):
            values = request.headers.getlist(name)
            if len(values) != 1 or not re.fullmatch(pattern, values[0]):
                raise ServiceError(400, "invalid_request")
            return values[0]
        attempt_id = field("x-atom-attempt", r"[0-9a-f]{32}")
        version = int(field("x-atom-export-version", r"[1-9][0-9]{0,18}"))
        revision = field("x-atom-registered-revision", r"[0-9a-f]{64}")
        if version > 9223372036854775807:
            raise ServiceError(400, "invalid_request")
        async with transfer() as lifecycle:
            attempt = await control(lifecycle.registry.authorize_confirmation, grant, version, revision)
            if attempt.id != attempt_id:
                raise ServiceError(409, "ownership_conflict")
            payload = await _read_body(request, "application/octet-stream", MAX_ARCHIVE_BYTES)
            confirmed = await control(lifecycle.confirm_checkpoint, grant,
                CheckpointExport(attempt_id, version, revision, payload), registered_revision=revision)
            return JSONResponse({"attempt_id": confirmed.id, "state": confirmed.state,
                                 "version": confirmed.version, "revision": confirmed.checkpoint_revision})

    @app.get("/v1/attempts/{attempt_id}")
    async def status(attempt_id: str, request: Request):
        grant = signed_header(request)
        lifecycle = getattr(app.state, "lifecycle", None)
        if lifecycle is None:
            raise ServiceError(503, "broker_not_ready")
        attempt = await control(lifecycle.status, grant, attempt_id)
        return {"attempt_id": attempt.id, "state": attempt.state, "deadline": attempt.deadline}

    @app.post("/v1/attempts/{attempt_id}/release")
    async def release(attempt_id: str, request: Request):
        grant = signed_header(request)
        lifecycle = getattr(app.state, "lifecycle", None)
        if lifecycle is None:
            raise ServiceError(503, "broker_not_ready")
        attempt = await control(lifecycle.release, grant, attempt_id)
        return {"attempt_id": attempt.id, "state": attempt.state}

    @app.post("/v1/attempts/{attempt_id}/files")
    async def files(attempt_id: str, request: Request):
        grant = signed_header(request)
        async with transfer() as lifecycle:
            attempt = await control(lifecycle.registry.authorize, grant)
            if attempt.id != attempt_id:
                raise ServiceError(409, "ownership_conflict")
            value = _json(await _read_body(request, "application/json", 50 * 1024 * 1024))
            if (not isinstance(value, dict) or set(value) != {"operation_id", "tool_call_id", "operation"}
                    or not isinstance(value["operation_id"], str)
                    or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value["operation_id"])
                    or not isinstance(value["tool_call_id"], str)
                    or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value["tool_call_id"])):
                raise ServiceError(400, "invalid_request")
            try:
                validate(value["operation"])
            except (ValueError, TypeError, RecursionError):
                raise ServiceError(400, "invalid_request") from None
            outcome = await control(lifecycle.file_operation, grant, attempt_id,
                                    value["operation_id"], value["tool_call_id"], value["operation"])
            return JSONResponse({"tool_call_id": value["tool_call_id"], "outcome": outcome})

    return app
