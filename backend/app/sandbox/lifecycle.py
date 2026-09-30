"""Durable lifecycle coordination; service scheduling and file operations follow."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import threading

from .docker_driver import DockerDriver, DriverError, OwnedContainer
from .grants import Grant
from .registry import Attempt, Registry, RegistryError


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
    def __init__(self, registry: Registry, driver: DockerDriver, *, batch_size: int = 100):
        if registry.broker_id != driver.broker_id:
            raise LifecycleError("broker_identity_mismatch")
        if type(batch_size) is not int or not 1 <= batch_size <= 1000:
            raise LifecycleError("invalid_reconciliation_batch")
        self.registry, self.driver = registry, driver
        self._batch_size = batch_size
        self._control = threading.Lock()
        self._lease = _ProcessLease(registry.path.with_suffix(".lease"))
        self._ready = False
        self._initialized = False
        self._closed = False
        self._cursor = ""

    @property
    def ready(self) -> bool:
        return self._ready and not self._closed

    @contextmanager
    def _exclusive(self):
        if not self._control.acquire(timeout=3):
            raise LifecycleError("broker_busy")
        try:
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
            except (DriverError, RegistryError, LifecycleError):
                try:
                    self._stop(attempt.id)
                except (DriverError, RegistryError, LifecycleError):
                    self._ready = False
                raise LifecycleError("provision_failed") from None

    def revoke(self, grant_id: str) -> Attempt | None:
        # Persist cancellation even if a bounded control operation currently holds the lock.
        if self._closed:
            raise LifecycleError("broker_closed")
        self.registry.revoke(grant_id)
        with self._exclusive():
            attempt = self.registry.find_grant(grant_id)
            return self._stop(attempt.id) if attempt else None

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

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        try:
            self.close()
        except BaseException as cleanup:
            if value is not None:
                raise BaseExceptionGroup("Broker operation and shutdown failed", [value, cleanup]) from None
            raise
