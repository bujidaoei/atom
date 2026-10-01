"""Owned audit export cycles; no automatic enablement or operator configuration API."""
import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import math
from pathlib import Path

from .audit_delivery import AuditDeliveryRepository, AuditDeliveryError
from .audit_destination import AuditDestination
from .audit_sender import AuditSendError, send_audit_events
from .bounded_operations import BoundedOperations


class AuditExporterError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExportResult:
    outcome: str
    event_count: int
    unenrolled_remaining: bool
    capacity_reached: bool


@dataclass
class _Cycle:
    database: Future | None = None


class AuditExporter:
    def __init__(self, path, destination: AuditDestination, *, ca_file=None):
        if type(destination) is not AuditDestination:
            raise AuditExporterError('invalid_audit_destination')
        self._path = Path(path)
        self._destination = destination
        self._ca_file = ca_file
        self._owner = BoundedOperations(capacity=1)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='atom-audit-db')
        self._repository = None
        self._workers = set()
        self._loop = None
        self._closed = False
        self._stop = asyncio.Event()
        self._scheduler = None
        self.last_error = None

    @property
    def pending_count(self):
        return self._owner.pending_count

    def _bind_loop(self):
        loop = asyncio.get_running_loop()
        if self._loop is not None and self._loop is not loop:
            raise AuditExporterError('audit_export_loop_mismatch')
        self._loop = loop

    async def run_once(self):
        self._bind_loop()
        token = self._owner.acquire()
        if token is None:
            raise AuditExporterError('audit_export_not_admitted')
        worker = asyncio.create_task(self._cycle(token))
        self._workers.add(worker)
        worker.add_done_callback(self._finished)
        # A cancelled waiter must not abort an in-flight send or lose its local ack.
        return await asyncio.shield(worker)

    def _finished(self, worker):
        self._workers.discard(worker)
        if not worker.cancelled():
            worker.exception()  # Consume detached failure without exposing remote diagnostics.

    def start(self, interval=5):
        self._bind_loop()
        if type(interval) not in (int, float) or not math.isfinite(interval) or not .01 <= interval <= 300:
            raise AuditExporterError('invalid_audit_schedule_interval')
        if self._closed or self.last_error == 'audit_export_configuration' or self._scheduler is not None:
            raise AuditExporterError('audit_schedule_not_admitted')
        self._scheduler = asyncio.create_task(self._schedule(interval))

    async def _schedule(self, interval):
        while not self._closed:
            try:
                await self.run_once()
            except AuditExporterError:
                if self._closed or self.last_error == 'audit_export_configuration':
                    return
            try:
                await asyncio.wait_for(self._stop.wait(), interval)
                return
            except TimeoutError:
                pass

    async def close(self, timeout=45):
        self._bind_loop()
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not .01 <= timeout <= 60:
            raise AuditExporterError('invalid_audit_close_timeout')
        self._closed = True
        self._stop.set()
        self._owner.close_admission()
        try:
            async with asyncio.timeout(timeout):
                await self._owner.drain(timeout)
                if self._scheduler is not None:
                    await asyncio.shield(self._scheduler)
        except TimeoutError:
            raise RuntimeError('bounded_drain_timeout') from None
        self._executor.shutdown(wait=False)

    async def _database(self, cycle, operation, **arguments):
        def call():
            if self._repository is None:
                self._repository = AuditDeliveryRepository(self._path,
                    destination_id=self._destination.destination_id,
                    scope_kind=self._destination.scope_kind, scope_id=self._destination.scope_id)
            return getattr(self._repository, operation)(**arguments)
        # Keep the concurrent future, not just an asyncio wrapper that may be cancelled.
        cycle.database = self._executor.submit(call)
        return await asyncio.shield(asyncio.wrap_future(cycle.database))

    async def _cycle(self, token):
        cycle = _Cycle()
        try:
            async with asyncio.timeout(40):
                enrollment = await self._database(cycle, 'enroll')
                # Shutdown stops follow-on network work when only enrollment was underway.
                if self._closed:
                    return ExportResult('closed', 0, enrollment['remaining'], enrollment['capacity_reached'])
                lease = await self._database(cycle, 'claim', lease_seconds=60)
                if not lease.events:
                    return ExportResult('idle', 0, enrollment['remaining'], enrollment['capacity_reached'])
                ids = [event['event_id'] for event in lease.events]
                try:
                    await send_audit_events(self._destination, lease.events, ca_file=self._ca_file)
                except AuditSendError as error:
                    if not error.retryable:
                        self._owner.close_admission()
                        self.last_error = 'audit_export_configuration'
                        raise AuditExporterError(self.last_error) from None
                    await self._database(cycle, 'retry', event_ids=ids, lease_owner=lease.owner)
                    self.last_error = 'audit_export_retry_pending'
                    return ExportResult('retry', len(ids), enrollment['remaining'], enrollment['capacity_reached'])
                await self._database(cycle, 'acknowledge', event_ids=ids, lease_owner=lease.owner)
                self.last_error = None
                return ExportResult('delivered', len(ids), enrollment['remaining'], enrollment['capacity_reached'])
        except AuditDeliveryError:
            self.last_error = 'audit_export_storage_unavailable'
            raise AuditExporterError(self.last_error) from None
        except TimeoutError:
            self.last_error = 'audit_export_cycle_timeout'
            raise AuditExporterError(self.last_error) from None
        except asyncio.CancelledError:
            self.last_error = 'audit_export_interrupted'
            raise
        except AuditExporterError:
            raise
        except Exception:
            self.last_error = 'audit_export_failed'
            raise AuditExporterError(self.last_error) from None
        finally:
            future = cycle.database
            if future is not None and not future.done():
                future.add_done_callback(lambda _done: self._owner.release(token))
            else:
                self._owner.release(token)
