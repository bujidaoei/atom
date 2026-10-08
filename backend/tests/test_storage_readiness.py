"""Fault-injection checks are distinct from actual COS/live acceptance."""
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
from types import SimpleNamespace
import asyncio

import pytest

from app.artifacts import ArtifactError
from app.cos_artifact_worker import service_error
from app.storage_readiness import StorageReadiness, StorageUnavailable
from app.services.orchestrator import Orchestrator
from test_adoption_repository import snapshot


@pytest.mark.parametrize('status,code,expected', [
    (403, 'InvalidAccessKeyId', 'artifact_credentials_invalid'),
    (403, 'ExpiredToken', 'artifact_credentials_invalid'),
    (403, 'SignatureDoesNotMatch', 'artifact_signature_invalid'),
    (403, 'AccessDenied', 'artifact_access_denied'),
    (403, 'AccessForbidden', 'artifact_access_denied'),
    (404, 'NoSuchKey', 'artifact_not_found'),
    (500, 'secret-signed-url', 'artifact_io_error'),
    (403, 'unknown-secret', 'artifact_io_error'),
])
def test_fixed_error_classification(status, code, expected):
    error = SimpleNamespace(get_status_code=lambda: status, get_error_code=lambda: code)
    assert service_error(error).code == expected


def probe(tmp_path, action):
    payload, artifact = snapshot(b'<html>registered</html>')
    database = tmp_path / 'ledger.db'
    with sqlite3.connect(database) as db:
        db.execute('CREATE TABLE revision_artifacts (key TEXT,revision TEXT,size INTEGER)')
        db.execute('INSERT INTO revision_artifacts VALUES (?,?,?)',
                   (artifact.key, artifact.revision, artifact.size))
    return StorageReadiness(database, SimpleNamespace(read=action), interval=1), payload, artifact


def test_concurrent_probe_uses_one_real_read_and_cache(tmp_path):
    reads = []
    payload, artifact = snapshot(b'<html>registered</html>')
    readiness, _, _ = probe(tmp_path, lambda key: reads.append(key) or payload)
    with ThreadPoolExecutor(max_workers=12) as pool:
        assert all(pool.map(lambda _: readiness.check(), range(24)))
    assert reads == [artifact.key]


def test_credential_failure_recovers_after_finite_cache_expiry(tmp_path, monkeypatch, caplog):
    clock = [100]
    monkeypatch.setattr('app.storage_readiness.time.monotonic', lambda: clock[0])
    def denied(_key):
        raise ArtifactError('artifact_credentials_invalid')
    readiness, payload, _ = probe(tmp_path, denied)
    with pytest.raises(StorageUnavailable, match='存储认证失效'):
        readiness.require_available()
    readiness.store.read = lambda _: payload
    assert readiness.check() is False
    clock[0] += 2
    readiness.require_available()
    assert len(caplog.records) == 2
    assert all(record.message.startswith('artifact_readiness_changed ') for record in caplog.records)


def test_digest_and_metadata_fail_closed(tmp_path):
    readiness, payload, artifact = probe(tmp_path, lambda _: b'corrupt')
    assert readiness.check() is False
    readiness._checked = None
    readiness.store.read = lambda _: payload
    with sqlite3.connect(readiness.database) as db:
        db.execute('UPDATE revision_artifacts SET size=size+1')
    assert readiness.check() is False


def test_missing_inventory_and_database_do_not_create_files(tmp_path):
    missing = tmp_path / 'absent.db'
    readiness = StorageReadiness(missing, SimpleNamespace(read=lambda _: pytest.fail('no object')))
    assert readiness.check() is False
    assert not missing.exists()


def test_create_project_denied_before_business_rows(signed_in, monkeypatch):
    from app.main import app
    from app.db import session_scope
    from app.models import Project
    from sqlalchemy import select, func
    def denied():
        raise StorageUnavailable('文件存储认证失效，请管理员更新存储凭据后重试')
    monkeypatch.setattr(app.state, 'execution', SimpleNamespace(readiness=SimpleNamespace(require_available=denied)))
    response = signed_in.post('/api/projects', json={'prompt': 'build a real project'})
    assert response.status_code == 503 and '存储认证失效' in response.json()['detail']
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(Project)) == 0


def test_execution_admission_precedes_spawn_and_model(tmp_path, monkeypatch):
    runner = Orchestrator()
    def denied():
        raise StorageUnavailable('storage unavailable')
    runner.execution = SimpleNamespace(readiness=SimpleNamespace(require_available=denied))
    monkeypatch.setattr(runner, '_spawn', lambda *_a, **_k: pytest.fail('must not spawn'))
    with pytest.raises(StorageUnavailable):
        asyncio.run(runner.start_plan('project', 'owner'))


def test_health_reports_storage_failure(monkeypatch):
    from app.main import app, health
    from app.config import get_settings
    from app.services.runtime_client import runtime_client
    async def ready(): return True
    monkeypatch.setattr(runtime_client, 'healthy', ready)
    monkeypatch.setattr(get_settings(), 'sandbox_mode', 'broker')
    monkeypatch.setattr(get_settings(), 'storage_backend', 'cos')
    monkeypatch.setattr(app.state, 'execution', SimpleNamespace(
        coordinator=SimpleNamespace(broker=SimpleNamespace(require_ready=ready)),
        readiness=SimpleNamespace(check=lambda: False)), raising=False)
    response = asyncio.run(health())
    assert response.status_code == 503
    assert json.loads(response.body) == {'ok': False, 'runtime': True, 'broker': True, 'storage': False}
