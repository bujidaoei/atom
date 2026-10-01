"""Exclusive startup and finite-life ownership for the trusted verifier."""
from __future__ import annotations

from threading import RLock

from .sandbox.daemon_lease import DaemonLeaseError, VerifierCoordinatorLease
from .verifier_supervisor import SupervisorError, VerifierSupervisor


class VerifierCoordinator:
    """Keep the daemon identity held across reconciliation and verification.

    The local lock serializes shutdown with registration. Docker's fixed-name
    lease excludes a second process on the same daemon; process death releases
    the lease, and the successor reaps the abandoned browser before work starts.
    """

    def __init__(self, supervisor: VerifierSupervisor):
        if type(supervisor) is not VerifierSupervisor:
            raise SupervisorError('invalid_supervisor_configuration')
        self.supervisor = supervisor
        self.lease = VerifierCoordinatorLease(supervisor.verifier_id,
                                             supervisor.image,
                                             executable=supervisor.executable)
        self._lock = RLock()
        self._started = False

    def _require_lease(self) -> None:
        if not self._started:
            raise SupervisorError('verifier_coordinator_lease_lost')
        try:
            self.lease.assert_owner()
        except DaemonLeaseError:
            raise SupervisorError('verifier_coordinator_lease_lost') from None

    def start(self) -> int:
        with self._lock:
            if self._started:
                raise SupervisorError('verifier_coordinator_already_started')
            self.lease.acquire()
            self._started = True
            try:
                return self.supervisor.reap_orphans(lease=self.lease)
            except BaseException:
                self._started = False
                self.lease.close()
                raise

    def verify_and_register(self, *, assignment, store, authority,
                            budget_seconds: int = 30):
        with self._lock:
            self._require_lease()
            return self.supervisor.verify_and_register(
                assignment=assignment, store=store, authority=authority,
                budget_seconds=budget_seconds, lease=self.lease)

    def close(self) -> None:
        with self._lock:
            self._started = False
            self.lease.close()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, _type, _value, _traceback):
        self.close()
