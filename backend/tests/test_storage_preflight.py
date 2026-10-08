"""Preflight receipts must cover a fresh PUT and the real SQLite inventory."""
import sqlite3
import sys

import pytest

from app.artifacts import ArtifactError
from app.artifact_transfer import TransferError
from app.storage_preflight import verify_storage
from app.storage_readiness import StorageReadiness
from test_adoption_repository import prepared, snapshot
from test_revision_migrations import legacy
from test_artifact_transfer import Destination


def destination(prepared):
    path, _, _, heat_payload, heat_artifact = prepared
    main_payload, main_artifact = snapshot(b'<html>main</html>')
    store = Destination()
    store.payloads.update({heat_artifact.key: heat_payload, main_artifact.key: main_payload})
    return path, store


def test_preflight_fresh_upload_full_inventory_without_business_writes(prepared):
    path, store = destination(prepared)
    with sqlite3.connect(path) as db:
        before = db.execute('SELECT * FROM revision_records ORDER BY id').fetchall()
    first = verify_storage(path, store)
    second = verify_storage(path, store)
    assert first['ok'] and first['write_readback']
    assert first['artifact_count'] == 2 and first['schema_version'] == 12
    assert first['inventory_sha256'] == second['inventory_sha256']
    assert first['probe_key'] != second['probe_key']
    assert len(store.payloads) == 5
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT * FROM revision_records ORDER BY id').fetchall() == before


def test_read_permission_alone_cannot_pass_write_preflight(prepared):
    path, store = destination(prepared)
    def denied(_payload): raise ArtifactError('artifact_access_denied')
    store.put = denied
    with pytest.raises(ArtifactError, match='artifact_access_denied'):
        verify_storage(path, store)


def test_one_unreadable_registered_object_prevents_acceptance(prepared):
    path, store = destination(prepared)
    key = next(iter(store.payloads))
    read = store.read
    def missing(candidate):
        if candidate == key: raise ArtifactError('artifact_not_found')
        return read(candidate)
    store.read = missing
    with pytest.raises(TransferError, match='transfer_artifact_unavailable'):
        verify_storage(path, store)


def test_initialized_empty_inventory_can_admit_first_project(legacy):
    from app.migrations import migrate
    path, backup = legacy
    migrate(path, backup, target_version=11)
    for version in range(12, 20):
        migrate(path, path.parent / f'before-probe-v{version}.db', target_version=version)
    store = Destination()
    result = verify_storage(path, store)
    assert result['artifact_count'] == 0 and result['write_readback'] is True
    readiness = StorageReadiness(path, store)
    assert readiness.check() is True


@pytest.mark.skipif(sys.platform != 'linux', reason='real private durable store requires Linux')
def test_empty_installation_readiness_uses_durably_written_marker(legacy, tmp_path):
    from app.artifacts import ArtifactStore
    from app.migrations import migrate
    path, backup = legacy
    migrate(path, backup, target_version=11)
    root = tmp_path / 'private-artifacts'
    root.mkdir(mode=0o700)
    store = ArtifactStore(root)
    result = verify_storage(path, store)
    assert result['artifact_count'] == 0
    assert len(list(root.iterdir())) == 2
    assert StorageReadiness(path, store).check() is True
