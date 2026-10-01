"""Main-owned supervisor for a bounded set of operator-configured exporters."""
import asyncio
import ssl

from .audit_exporter import AuditExporter, AuditExporterError


class AuditExportService:
    def __init__(self, settings):
        destinations = settings.audit_destinations
        self._interval = settings.audit_export_interval_seconds
        self._ca_file = settings.audit_export_ca_file
        self._exporters = [AuditExporter(settings.db_path, destination, ca_file=self._ca_file)
                           for destination in destinations]
        self._started = False

    @property
    def pending_count(self):
        return sum(exporter.pending_count for exporter in self._exporters)

    async def start(self):
        if self._started:
            raise AuditExporterError('audit_service_already_started')
        if self._exporters:
            try:
                ssl.create_default_context(cafile=self._ca_file)
            except (OSError, ssl.SSLError):
                raise AuditExporterError('invalid_audit_trust_store') from None
        # No destination starts sending until every preflight has succeeded.
        for exporter in self._exporters:
            await exporter.prepare()
        for exporter in self._exporters:
            exporter.start(self._interval)
        self._started = True

    def stop_admission(self):
        for exporter in self._exporters:
            exporter.stop_admission()

    async def close(self):
        self.stop_admission()
        results = await asyncio.gather(*(exporter.close() for exporter in self._exporters), return_exceptions=True)
        failures = [result for result in results if isinstance(result, BaseException)]
        if len(failures) == 1:
            raise failures[0]
        if failures:
            raise BaseExceptionGroup('audit_export_shutdown_failed', failures)
