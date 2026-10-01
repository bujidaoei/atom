"""Durable ownership, verified input, file-operation receipts and cleanup."""
from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Callable
import os
import hashlib
import io
import json
import logging
from pathlib import Path
import re
import threading
import time
import uuid

from .docker_driver import DockerDriver, DriverError, OwnedContainer
from .grants import Grant
from .file_helper import FileError, validate
from .file_ops import FileOperations
from .registry import Attempt, Registry, RegistryError
from .seeding import MAX_SEED_BYTES, SeedOperations
from .checkpoints import CheckpointExport, CheckpointOperations
from ..snapshots import MAX_ARCHIVE_BYTES, SnapshotError, verify_snapshot


_LOG = logging.getLogger("atom.sandbox.lifecycle")


class LifecycleError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class _ProcessLease:
    def __init__(self, path: Path):
        if path.is_symlink():
            raise LifecycleError("invalid_lease_path")
        self.file = None
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
            self.file = os.fdopen(descriptor, "r+b", buffering=0)
            if os.fstat(descriptor).st_size == 0:
                self.file.write(b"0")
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            if self.file is not None:
                self.file.close()
            raise LifecycleError("broker_already_owned") from None

    def close(self):
        if self.file is not None:
            self.file.close()
            self.file = None


class Lifecycle:
    def __init__(self, registry: Registry, driver: DockerDriver, *, batch_size: int = 100,
                 lease_alive: Callable[[], bool] | None = None):
        if registry.broker_id != driver.broker_id:
            raise LifecycleError("broker_identity_mismatch")
        if type(batch_size) is not int or not 1 <= batch_size <= 1000:
            raise LifecycleError("invalid_reconciliation_batch")
        self.registry, self.driver = registry, driver
        self._batch_size = batch_size
        self._lease_alive = lease_alive or (lambda: True)
        self._control = threading.Lock()
        self._lease = _ProcessLease(registry.path.with_suffix(".lease"))
        self._ready = False
        self._initialized = False
        self._closed = False
        self._cursor = ""

    @property
    def ready(self) -> bool:
        return self._ready and not self._closed and self._lease_alive()

    @contextmanager
    def _exclusive(self):
        if not self._lease_alive():
            self._ready = False
            raise LifecycleError("broker_identity_lease_lost")
        if not self._control.acquire(timeout=3):
            raise LifecycleError("broker_busy")
        try:
            if not self._lease_alive():
                self._ready = False
                raise LifecycleError("broker_identity_lease_lost")
            if self._closed:
                raise LifecycleError("broker_closed")
            yield
        except RegistryError as error:
            if error.code == "registry_unavailable":
                self._ready = False
            raise
        finally:
            self._control.release()

    def _stop(self, attempt_id: str) -> Attempt:
        try:
            return self._stop_known(attempt_id)
        except RegistryError:
            self._ready = False
            raise LifecycleError("termination_record_failed") from None

    def _stop_known(self, attempt_id: str) -> Attempt:
        attempt = self.registry.request_termination(attempt_id)
        if attempt.state == "terminated":
            return attempt
        try:
            self.driver.terminate(attempt)
        except DriverError:
            self._ready = False
            self.registry.record_termination(attempt.id, attempt.version, confirmed=False)
            raise LifecycleError("termination_unknown") from None
        return self.registry.record_termination(attempt.id, attempt.version, confirmed=True)

    def _reconcile(self, *, retire_all: bool):
        self._ready = False
        self.registry.expire_due()
        attempts = self.registry.unterminated(limit=self._batch_size, after_id="" if retire_all else self._cursor)
        self._cursor = attempts[-1].id if attempts and not retire_all else ""
        failure = None
        for attempt in attempts:
            try:
                stop = retire_all or attempt.state in {"terminating", "termination_unknown"}
                if not stop:
                    state = self.driver.inspect(attempt)
                    stop = state is None or not state.running or state.paused
                if stop:
                    self.registry.revoke(attempt.grant_id)
                    self._stop(attempt.id)
            except (DriverError, RegistryError, LifecycleError):
                failure = "reconciliation_failed"
        try:
            inventory = self.driver.owned_inventory()
            if len(inventory) > self._batch_size:
                failure = "reconciliation_incomplete"
            for container in inventory[:self._batch_size]:
                recorded = self.registry.find(container.attempt_id)
                if recorded is None or recorded.state == "terminated":
                    self.registry.observe_orphan(container.id, container.attempt_id)
        except (DriverError, RegistryError):
            failure = "reconciliation_failed"
        # Include records absent from inventory: a prior process may have died
        # after removal but before committing its confirmation.
        for orphan in self.registry.pending_orphans(limit=self._batch_size):
            try:
                self.driver.terminate_orphan(OwnedContainer(orphan.id, orphan.attempt_id))
            except DriverError:
                self.registry.record_orphan_termination(orphan.id, orphan.version, confirmed=False)
                failure = "orphan_recovery_required"
            else:
                self.registry.record_orphan_termination(orphan.id, orphan.version, confirmed=True)
        if self.registry.pending_orphans(limit=1):
            failure = failure or "reconciliation_incomplete"
        if self.registry.has_pending_termination() or (retire_all and self.registry.unterminated(limit=1)):
            failure = failure or "reconciliation_incomplete"
        if failure:
            raise LifecycleError(failure)
        self._ready = True

    def start(self):
        with self._exclusive():
            if self._initialized:
                return
            self._reconcile(retire_all=True)
            self._initialized = True

    def sweep(self):
        with self._exclusive():
            self._reconcile(retire_all=not self._initialized)
            self._initialized = True

    def provision(self, grant: Grant) -> Attempt:
        """Prepare an owned container; input snapshot import must precede ready state."""
        with self._exclusive():
            if not self.ready:
                raise LifecycleError("broker_not_ready")
            attempt = self.registry.admit(grant)
            if attempt.state not in {"intent", "provisioning", "ready"}:
                raise LifecycleError("attempt_closed")
            if attempt.state == "intent":
                attempt = self.registry.transition(grant, attempt.version, "provisioning")
            try:
                self.driver.ensure(attempt)
                current = self.registry.admit(grant)  # Recheck expiry/revoke after the external effect.
                if current.version != attempt.version:
                    raise LifecycleError("ownership_changed")
                return current
            except (DriverError, RegistryError, LifecycleError) as error:
                _LOG.warning("broker_provision_failed type=%s code=%s",
                             type(error).__name__, error.code)
                try:
                    self._stop(attempt.id)
                except (DriverError, RegistryError, LifecycleError):
                    self._ready = False
                raise LifecycleError("provision_failed") from None

    def seed(self, grant: Grant, payload: bytes) -> Attempt:
        """Admit execution only after exact verified input and a durable ready commit."""
        if not isinstance(payload, bytes) or len(payload) > MAX_SEED_BYTES:
            raise LifecycleError("invalid_seed_input")
        with self._exclusive():
            if not self.ready:
                raise LifecycleError("broker_not_ready")
            attempt = self.registry.admit(grant)
            if attempt.state != "provisioning":
                raise LifecycleError("attempt_not_provisioning")
            try:
                SeedOperations(self.driver).execute(attempt, payload)
                return self.registry.transition(grant, attempt.version, "ready")
            except BaseException as error:
                _LOG.warning("broker_seed_failed type=%s code=%s",
                             type(error).__name__,
                             error.code if isinstance(error, (DriverError, RegistryError, LifecycleError)) else 'unknown')
                self._retire_operation(attempt)
                if not isinstance(error, Exception):
                    raise
                raise LifecycleError("seed_outcome_unknown") from None

    def export_checkpoint(self, grant: Grant) -> CheckpointExport:
        with self._exclusive():
            if not self.ready:
                raise LifecycleError("broker_not_ready")
            attempt = self.registry.authorize_checkpoint(grant)
            if attempt.state == "ready":
                attempt = self.registry.transition(grant, attempt.version, "quiescing")
            try:
                exported = CheckpointOperations(self.driver).execute(attempt)
                current = self.registry.authorize_checkpoint(grant)
                if current.version != attempt.version or current.state != "quiescing":
                    raise LifecycleError("checkpoint_ownership_changed")
                return exported
            except BaseException as error:
                _LOG.warning("broker_checkpoint_failed type=%s code=%s",
                             type(error).__name__,
                             error.code if isinstance(error, (DriverError, RegistryError,
                                                              LifecycleError, SnapshotError)) else 'unknown')
                self._retire_operation(attempt)
                if not isinstance(error, Exception):
                    raise
                raise LifecycleError("checkpoint_outcome_unknown") from None

    def confirm_checkpoint(self, grant: Grant, exported: CheckpointExport, *, registered_revision: str) -> Attempt:
        """Trusted coordinator only, after a durable registration receipt.

        The matching digest is an assertion by the coordinator, not a capability
        available to runtime. This method neither commits API state nor releases.
        """
        if (not isinstance(exported, CheckpointExport) or not isinstance(exported.payload, bytes)
                or len(exported.payload) > MAX_ARCHIVE_BYTES
                or type(exported.attempt_version) is not int or exported.attempt_version < 1
                or not isinstance(registered_revision, str) or exported.revision != registered_revision):
            raise LifecycleError("invalid_checkpoint_acknowledgement")
        with self._exclusive():
            if not self.ready:
                raise LifecycleError("broker_not_ready")
            attempt = self.registry.find_grant(grant.jti)
            if attempt is None or attempt.id != exported.attempt_id or attempt.grant_fingerprint != grant.fingerprint():
                raise LifecycleError("checkpoint_scope_mismatch")
            try:
                verified = verify_snapshot(io.BytesIO(exported.payload))
            except SnapshotError:
                raise LifecycleError("invalid_checkpoint_acknowledgement") from None
            if verified.revision != registered_revision:
                raise LifecycleError("invalid_checkpoint_acknowledgement")
            return self.registry.confirm_checkpoint(grant, exported.attempt_version, registered_revision)

    def revoke(self, grant_id: str) -> Attempt | None:
        # Persist cancellation even if a bounded control operation currently holds the lock.
        if self._closed:
            raise LifecycleError("broker_closed")
        self.registry.revoke(grant_id)
        with self._exclusive():
            attempt = self.registry.find_grant(grant_id)
            return self._stop(attempt.id) if attempt else None

    def status(self, grant: Grant, attempt_id: str) -> Attempt:
        with self._exclusive():
            if not self.ready:
                raise LifecycleError("broker_not_ready")
            attempt = self.registry.authorize(grant)
            if attempt.id != attempt_id:
                raise RegistryError("attempt_scope_mismatch")
            state = self.driver.inspect(attempt)
            if state is None or not state.running or state.paused:
                self._retire_operation(attempt)
                raise LifecycleError("worker_unavailable")
            return attempt

    def release(self, grant: Grant, attempt_id: str) -> Attempt:
        if self._closed:
            raise LifecycleError("broker_closed")
        self.registry.request_scoped_termination(grant, attempt_id)
        with self._exclusive():
            return self._stop(attempt_id)

    def _retire_operation(self, attempt: Attempt):
        self._ready = False
        try:
            self.registry.revoke(attempt.grant_id)
            self._stop(attempt.id)
        except (RegistryError, LifecycleError, DriverError):
            # Losing database access cannot justify leaving a possibly-mutating
            # helper alive. Persisted running intent will be reconciled later.
            try:
                self.driver.terminate(attempt)
            except DriverError:
                pass

    def file_operation(self, grant: Grant, attempt_id: str, operation_id: str,
                       tool_call_id: str, operation: dict) -> dict:
        """Trusted verified-grant entry; never retry an uncertain external effect."""
        try:
            validate(operation)
            if not isinstance(tool_call_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", tool_call_id):
                raise FileError("invalid_tool_call_id")
            encoded = json.dumps({"tool_call_id": tool_call_id, "operation": operation},
                                 sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
            # Detach from caller-owned mutable dictionaries before hashing/IO.
            operation = json.loads(encoded)["operation"]
        except (ValueError, TypeError, RecursionError):
            raise FileError("invalid_operation") from None
        fingerprint = hashlib.sha256(encoded.encode("ascii")).hexdigest()
        reservation = {"read_bytes": 12 * 1024 * 1024, "write": 4096}.get(operation["op"], 2 * 1024 * 1024)
        with self._exclusive():
            if not self.ready:
                raise LifecycleError("broker_not_ready")
            attempt = self.registry.authorize(grant)
            receipt, fresh = self.registry.begin_operation(grant, attempt_id, operation_id, fingerprint, reservation)
            if not fresh:
                if receipt.state == "completed":
                    try:
                        return json.loads(receipt.result_json)
                    except (TypeError, ValueError):
                        self._retire_operation(attempt)
                        raise LifecycleError("invalid_operation_receipt") from None
                self._retire_operation(attempt)
                raise LifecycleError("operation_outcome_unknown")
            try:
                # Recheck after durable admission and before the external effect.
                attempt = self.registry.authorize(grant)
                try:
                    data = FileOperations(self.driver).execute(attempt, operation)
                    outcome = {"ok": True, "data": data}
                except FileError as error:
                    if operation["op"] == "write" and str(error) != "file_conflict":
                        raise
                    outcome = {"ok": False, "error": str(error)}
                self.registry.complete_operation(grant, attempt_id, operation_id, outcome)
                return outcome
            except BaseException as error:
                self._retire_operation(attempt)
                if not isinstance(error, Exception):
                    raise
                raise LifecycleError("operation_outcome_unknown") from None

    def close(self):
        if self._closed:
            return
        with self._exclusive():
            try:
                self._reconcile(retire_all=True)
            finally:
                self._ready = False
                self._closed = True
                self._lease.close()

    def abandon_after_lease_loss(self):
        """Release only the local process lock; never touch Docker without daemon ownership."""
        if self._lease_alive():
            raise LifecycleError("broker_identity_lease_still_active")
        self._ready = False
        self._closed = True
        self._lease.close()

    def verify_audit_archive(self, payload: bytes, *, expected_sha256: str) -> dict:
        """Trusted administrative entry; never accepts runtime grants or caller-selected code/mounts."""
        from ..audit_archive import decode_archive
        from .audit_recovery import AuditRecoveryOperations
        decode_archive(payload, expected_sha256=expected_sha256)
        identity = uuid.uuid4().hex
        now = int(time.time())
        grant = Grant(identity, 'audit-recovery', 'audit-recovery', identity, identity, 1, expected_sha256, now, now+60)
        attempt = self.provision(grant)
        with self._exclusive():
            try:
                current = self.registry.admit(grant)
                result = AuditRecoveryOperations(self.driver).execute(current,payload,expected_sha256=expected_sha256)
            finally:
                # No verification response is released until worker termination is confirmed/durable.
                self._stop(attempt.id)
            return dict(protocol='audit-recovery-v2',image=self.driver.image,policy_digest=self.driver.policy_digest,
                attempt_id=attempt.id,result=result)

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        try:
            self.close()
        except BaseException as cleanup:
            if value is not None:
                raise BaseExceptionGroup("Broker operation and shutdown failed", [value, cleanup]) from None
            raise
