"""Legacy link import must prove exact old bytes before creating history."""
import sqlite3
from datetime import datetime, timezone

import pytest

from app.legacy_publications import (LegacyPublicationError, import_live_legacy,
                                     inspect_live_legacy)
from app.migrations import migrate
from app.project_origins import ProjectOriginRepository
from test_adoption_repository import Store, prepared, snapshot
from test_revision_migrations import legacy


@pytest.fixture
def legacy_site(prepared, tmp_path):
    path, _main, _heat, _payload, _artifact = prepared
    for version in (13, 14, 15, 16, 17):
        migrate(path, tmp_path / f'before-v{version}.db', target_version=version)
    content = b'<html>main</html>'
    payload, artifact = snapshot(content)
    published = tmp_path / 'published'
    site = published / 'old-site'
    site.mkdir(parents=True)
    (site / 'index.html').write_bytes(content)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE projects SET status='ready' WHERE id='project'")
        db.execute("INSERT INTO publications(slug,project_id,live,created_at) VALUES ('old-site','project',1,?)",
                   (datetime.now(timezone.utc).isoformat(),))
    ProjectOriginRepository(path, first_port=20000, last_port=20003).reserve('project')
    return path, published, site, Store(artifact.key, payload)


@pytest.mark.parametrize('prepared', [12], indirect=True)
def test_import_live_legacy_preserves_link_and_publishes_exact_snapshot(legacy_site):
    path, published, _site, store = legacy_site
    ready = []
    candidate = inspect_live_legacy(path, published, store,
                                    project_id='project', slug='old-site')
    assert candidate.file_count == 1 and candidate.revision_id == 'main-root'
    receipt = import_live_legacy(path, published, store, project_id='project',
                                 slug='old-site', readiness=lambda: ready.append(True))
    assert receipt.slug == 'old-site' and receipt.revision_id == 'main-root'
    assert ready == [True]
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT slug,live,generation FROM release_publications').fetchone() == (
            'old-site', 1, 1)
        assert db.execute('SELECT current_revision_id FROM revision_workspaces '
                          'WHERE heat_id IS NULL').fetchone() == ('main-root',)
    with pytest.raises(LegacyPublicationError, match='already_present'):
        inspect_live_legacy(path, published, store, project_id='project', slug='old-site')


@pytest.mark.parametrize('prepared', [12], indirect=True)
def test_import_rejects_changed_or_withdrawn_old_site(legacy_site):
    path, published, site, store = legacy_site
    (site / 'index.html').write_bytes(b'changed')
    with pytest.raises(LegacyPublicationError, match='files_mismatch'):
        inspect_live_legacy(path, published, store, project_id='project', slug='old-site')
    (site / 'index.html').write_bytes(b'<html>main</html>')
    with sqlite3.connect(path) as db:
        db.execute("UPDATE publications SET live=0 WHERE slug='old-site'")
    with pytest.raises(LegacyPublicationError, match='not_ready'):
        inspect_live_legacy(path, published, store, project_id='project', slug='old-site')


@pytest.mark.parametrize('prepared', [12], indirect=True)
def test_ingress_failure_does_not_create_legacy_release(legacy_site):
    path, published, _site, store = legacy_site
    def unavailable():
        raise RuntimeError('ingress_unavailable')
    with pytest.raises(RuntimeError, match='ingress_unavailable'):
        import_live_legacy(path, published, store, project_id='project',
                           slug='old-site', readiness=unavailable)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM release_publications').fetchone() == (0,)
