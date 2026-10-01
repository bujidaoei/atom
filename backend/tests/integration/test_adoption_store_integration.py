"""Real Linux artifact-store adoption without enabling the production route."""
import sqlite3
import sys

import pytest

from app.adoption_repository import AdoptionRepository
from app.artifacts import ArtifactStore
from test_adoption_repository import prepared, adopt


@pytest.mark.skipif(sys.platform != 'linux', reason='ArtifactStore requires Linux filesystem semantics')
def test_real_store_pinned_heat_adoption_and_durable_replay(prepared, tmp_path):
    path, main, _, payload, artifact = prepared
    storage = tmp_path / 'artifacts'
    storage.mkdir(mode=0o700)
    store = ArtifactStore(storage)
    assert store.put(payload) == artifact
    first = adopt(AdoptionRepository(path), store)
    assert first.artifact == artifact and store.read(artifact.key) == payload
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        assert db.execute('SELECT current_revision_id FROM revision_workspaces WHERE id=?', (main,)).fetchone() == (first.revision_id,)
        assert db.execute("SELECT winner_heat_id FROM races WHERE id='race'").fetchone() == ('heat',)
        assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    reopened = ArtifactStore(storage)
    assert adopt(AdoptionRepository(path), reopened) == first
