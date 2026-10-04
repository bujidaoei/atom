"""Real Linux artifact bytes and SQLite catalogs, including request reuse scope."""
import sys

import pytest

from app.artifacts import ArtifactError, ArtifactStore
from app.revision_view import committed_catalog
from test_revision_repository import repository  # shared schema matrix
from test_snapshot_artifacts import archive


@pytest.mark.skipif(sys.platform != 'linux', reason='real Linux private artifact store')
def test_manifest_reuse_is_request_scoped_and_never_caches_authority(repository, tmp_path):
    repo, _, main, heat = repository
    root = tmp_path / 'objects'
    root.mkdir(mode=0o700)

    class CountingStore(ArtifactStore):
        reads = 0

        def read(self, key):
            self.reads += 1
            return super().read(key)

    store = CountingStore(root)
    artifact = store.put(archive())
    main_id = repo.bootstrap('owner', main, artifact)
    heat_id = repo.bootstrap('owner', heat, artifact)
    manifests = {}
    first = committed_catalog(repo, store, owner='owner', project_id='p', manifests=manifests)
    second = committed_catalog(repo, store, owner='owner', project_id='p', heat_id='heat', manifests=manifests)
    assert first['revisionId'] == main_id and second['revisionId'] == heat_id
    assert first['files'] == second['files'] and first['files']
    assert store.reads == 1
    denied = committed_catalog(repo, store, owner='foreign', project_id='p', manifests=manifests)
    assert denied['revisionId'] is None and denied['files'] == []
    assert store.reads == 1
    committed_catalog(repo, store, owner='owner', project_id='p', manifests={})
    assert store.reads == 2
    (root / (artifact.key + '.atomsnap')).write_bytes(b'corrupted')
    failed_request = {}
    with pytest.raises(ArtifactError):
        committed_catalog(repo, store, owner='owner', project_id='p', manifests=failed_request)
    assert failed_request == {}
