import asyncio
import json
import sqlite3
import threading
import time

from fastapi.testclient import TestClient
import pytest

from app.audit_configuration import audit_destinations
from app.audit_delivery import AuditDeliveryRepository
from app.audit_exporter import AuditExporterError
from app.audit_service import AuditExportService
from app.config import Settings, get_settings
from app.main import app
from app.migrations import migrate
from test_durable_auth_routes import durable_client, LOGIN, ORIGIN


ENTRY = dict(host='audit.example.org', path='/events', addresses=['8.8.8.8'],
             scope_kind='account', scope_id='user', token='synthetic-audit-token-at-least-32-characters')


def settings(**changes):
    return Settings(_env_file=None, session_mode='durable', console_origin=ORIGIN,
                    cookie_secure=True, **changes)


def test_operator_environment_parsing_and_redaction(monkeypatch):
    monkeypatch.setenv('ATOM_AUDIT_EXPORT_CONFIG', json.dumps([ENTRY]))
    config = settings()
    assert config.audit_destinations[0].host == ENTRY['host']
    assert ENTRY['token'] not in repr(config)
    assert 'audit_export_config' not in config.model_dump()
    assert len(config.audit_destinations) == 1


@pytest.mark.parametrize('value', ['{}', 'null', '[', '['+'['*1000,
    '[{"host":"x","host":"y"}]', json.dumps([ENTRY]*2),
    json.dumps([ENTRY|{'path': '/'+str(i)} for i in range(5)]),
    json.dumps([ENTRY|{'unknown': 'value'}]), json.dumps([ENTRY|{'addresses': '8.8.8.8'}]),
    json.dumps([ENTRY|{'addresses': ['127.0.0.1']}]), ' '*32769],
    ids=['object','null','broken','deep','duplicate-field','duplicate-destination','too-many',
         'unknown-field','wrong-address-shape','private-address','oversized'])
def test_malformed_operator_configuration_fails_without_token(value):
    with pytest.raises(ValueError) as caught:
        settings(audit_export_config=value)
    assert ENTRY['token'] not in str(caught.value)


def test_independent_credential_and_durable_cutover_required():
    config = settings()
    with pytest.raises(ValueError, match='independent_credentials'):
        settings(audit_export_config=json.dumps([ENTRY|{'token': config.secret}]))
    with pytest.raises(ValueError, match='requires_durable'):
        Settings(_env_file=None, session_mode='legacy', audit_export_config=json.dumps([ENTRY]))
    with pytest.raises(ValueError, match='absolute_ca_file'):
        settings(audit_export_ca_file='relative.pem')


@pytest.mark.parametrize('version', [4, 5, 6, 7])
def test_actual_main_startup_and_shutdown_owns_configured_export(durable_client, tmp_path, monkeypatch, version):
    client, path = durable_client
    if version in (5,6,7): migrate(path, tmp_path/'before-audit.db', target_version=version)
    user = client.post('/api/auth/register', json=LOGIN).json()['id']
    config = get_settings()
    monkeypatch.setattr(config, 'audit_export_config', json.dumps([ENTRY|{'scope_id': user}]))
    monkeypatch.setattr(app.state, 'audit_exports', None, raising=False)
    called = threading.Event()
    async def sender(*args, **kwargs):
        called.set()  # Outcome injection; actual main/SQLite ownership remains real.
    monkeypatch.setattr('app.audit_exporter.send_audit_events', sender)
    if version != 5:
        with pytest.raises(AuditExporterError, match='storage_unavailable'):
            with TestClient(app): pass
        assert not called.is_set()
        assert app.state.audit_exports.pending_count == 0
        with sqlite3.connect(path) as db: assert db.execute('PRAGMA user_version').fetchone() == (version,)
    else:
        with TestClient(app):
            assert called.wait(3)
            target = config.audit_destinations[0]
            repo = AuditDeliveryRepository(path, destination_id=target.destination_id,
                                           scope_kind='account', scope_id=user)
            deadline = time.monotonic()+3
            while repo.status()['delivered'] != 1 and time.monotonic() < deadline:
                time.sleep(.01)
            assert repo.status()['delivered'] == 1
        assert app.state.audit_exports.pending_count == 0
        assert app.state.execution is None


def test_all_preflights_precede_scheduling_and_every_close_attempted(monkeypatch):
    config = settings(audit_export_config=json.dumps([ENTRY, ENTRY|{'path': '/second'}]))
    service = AuditExportService(config)
    seen = []
    async def ready(): seen.append('ready')
    async def fail():
        seen.append('fail')
        raise AuditExporterError('fixture_storage_failure')
    monkeypatch.setattr(service._exporters[0], 'prepare', ready)
    monkeypatch.setattr(service._exporters[1], 'prepare', fail)
    monkeypatch.setattr(service._exporters[0], 'start', lambda *_: seen.append('started'))
    async def scenario():
        try:
            with pytest.raises(AuditExporterError): await service.start()
            assert seen == ['ready', 'fail']
        finally:
            await service.close()
    asyncio.run(scenario())


def test_close_failure_does_not_skip_other_destinations(monkeypatch):
    service = AuditExportService(settings(audit_export_config=json.dumps([ENTRY, ENTRY|{'path': '/second'}])))
    seen = []
    async def fail():
        seen.append('first')
        raise RuntimeError('fixture_drain_failure')
    original = service._exporters[1].close
    async def second():
        seen.append('second')
        await original()
    monkeypatch.setattr(service._exporters[0], 'close', fail)
    monkeypatch.setattr(service._exporters[1], 'close', second)
    async def scenario():
        with pytest.raises(RuntimeError, match='fixture_drain_failure'): await service.close()
        assert set(seen) == {'first', 'second'}
        assert all(exporter._closed for exporter in service._exporters)
        # First exporter had no submitted thread; restore close to finish pool bookkeeping.
        from app.audit_exporter import AuditExporter
        await AuditExporter.close(service._exporters[0])
    asyncio.run(scenario())
