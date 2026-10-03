"""Legacy link import must prove exact old bytes before creating history."""
import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.legacy_publications import (LegacyPublicationError, import_live_legacy,
                                     inspect_live_legacy)
import app.legacy_publications as legacy_module
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
def test_import_rejects_unexpected_and_oversized_files_before_reading(legacy_site,
                                                                       monkeypatch):
    path, published, site, store = legacy_site
    extra = site / 'unregistered.txt'
    extra.write_bytes(b'unregistered')
    with pytest.raises(LegacyPublicationError, match='files_mismatch'):
        inspect_live_legacy(path, published, store, project_id='project', slug='old-site')
    extra.unlink()
    original_open = legacy_module.os.open

    def forbid_large_open(file, *args, **kwargs):
        if str(file).endswith('index.html'):
            pytest.fail('oversized legacy file was opened')
        return original_open(file, *args, **kwargs)

    (site / 'index.html').write_bytes(b'content larger than saved snapshot')
    monkeypatch.setattr(legacy_module.os, 'open', forbid_large_open)
    with pytest.raises(LegacyPublicationError, match='files_mismatch'):
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


@pytest.mark.parametrize('prepared', [12], indirect=True)
def test_cli_requires_exact_operator_expectations_and_real_readiness(legacy_site,
                                                                       monkeypatch, capsys):
    path, published, _site, store = legacy_site
    monkeypatch.setattr(legacy_module, 'ObjectStorageSettings',
                        lambda: SimpleNamespace(storage_backend='cos'))
    monkeypatch.setattr(legacy_module, 'CosArtifactStore', lambda _settings: store)
    base = ['--database', str(path), '--published-root', str(published),
            '--project-id', 'project', '--slug', 'old-site']
    assert legacy_module.main(base) == 0
    assert 'main-root' in capsys.readouterr().out
    candidate = inspect_live_legacy(path, published, store,
                                    project_id='project', slug='old-site')
    apply = base + ['--apply', '--expect-revision', candidate.revision_id,
                    '--expect-artifact', candidate.artifact_key,
                    '--address', '192.0.2.1', '--first-port', '20000',
                    '--last-port', '20003']
    wrong = apply.copy()
    wrong[wrong.index('--expect-revision') + 1] = 'wrong'
    assert legacy_module.main(wrong) == 1
    assert 'expectation_changed' in capsys.readouterr().err
    def unavailable(*_args):
        return lambda: (_ for _ in ()).throw(legacy_module.IngressError('ingress_unavailable'))
    monkeypatch.setattr(legacy_module, '_readiness', unavailable)
    assert legacy_module.main(apply) == 1
    assert 'ingress_unavailable' in capsys.readouterr().err
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM release_publications').fetchone() == (0,)
    monkeypatch.setattr(legacy_module, '_readiness', lambda *_args: lambda: None)
    assert legacy_module.main(apply) == 0
    assert 'main-root' in capsys.readouterr().out


@pytest.mark.parametrize('prepared', [12], indirect=True)
def test_readiness_probes_both_reserved_tls_roles(legacy_site, monkeypatch):
    path, _published, _site, _store = legacy_site
    seen = []
    monkeypatch.setattr(legacy_module, 'probe_ip_routes',
                        lambda routes, address, **options: seen.append(
                            ([(route.purpose, route.port) for route in routes],
                             address, options['timeout_seconds'])))
    legacy_module._readiness(path, 'project', '192.0.2.1', 20000, 20003, None)()
    assert seen == [([('preview', 20000), ('public', 20001)], '192.0.2.1', 3)]
