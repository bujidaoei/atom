"""Real ASGI owner preview exchange, saved bytes and cross-port denial."""
from pathlib import Path
import sqlite3

import pytest
from starlette.testclient import TestClient

from app.access_repository import AccessRepository
from app.migrations import migrate
from app.preview_access import PreviewAccessRepository
from app.preview_entry import IpPreviewConfig, PreviewStartupError, create_ip_preview_app
from app.preview_service import PreviewService
from app.project_origins import ProjectOriginRepository
from app.project_port_hosts import ProjectPortHosts
from test_adoption_repository import prepared
from test_adoption_verification_repository import adopted
from test_revision_migrations import legacy
from test_rollback_v14_repository import historical
from test_v13_content_consumers import published
from test_verifier_authority import authorized


def test_preview_port_serves_only_one_exchanged_owner_revision(historical, tmp_path):
    path, store, _intent, _source, _displaced = historical
    for version in range(15, 19):
        migrate(path, tmp_path / f'before-v{version}.db', target_version=version)
    with sqlite3.connect(path) as db:
        revision = db.execute('SELECT revision_id FROM release_records WHERE project_id=? LIMIT 1',
                              ('project',)).fetchone()[0]
    origins = ProjectOriginRepository(path, first_port=20000, last_port=20003)
    assert origins.reserve('project').preview_port == 20000
    source = AccessRepository(path).create_console_session(user_id='user', lifetime_seconds=900)
    access = PreviewAccessRepository(path)
    grant = access.issue(owner_id='user', source_session_id=source.id,
                         project_id='project', revision_id=revision)
    service = PreviewService(access, store, ProjectPortHosts('192.0.2.10', origins))
    with TestClient(service, base_url='https://192.0.2.10:20000') as client:
        health = client.get('/_atom/health')
        assert health.status_code == 200
        assert health.json() == {'purpose':'preview', 'projectId':'project'}
        assert 'set-cookie' not in health.headers
        assert client.get('/_atom/health?x=1').status_code == 404
        assert client.get('http://192.0.2.10:20000/_atom/health').status_code == 404
        assert client.get('https://192.0.2.10:20001/_atom/health').status_code == 404
        assert client.get('/').status_code == 404
        opening = client.get('/_atom/open')
        assert opening.status_code == 200 and b'/_atom/exchange' in opening.content
        assert grant.secret.encode() not in opening.content
        assert client.post('/_atom/exchange', content=grant.secret,
                           headers={'Origin': 'https://192.0.2.11:20000',
                                    'Content-Type': 'application/octet-stream'}).status_code == 403
        exchange = client.post('/_atom/exchange', content=grant.secret,
                               headers={'Origin': 'https://192.0.2.10:20000',
                                        'Content-Type': 'application/octet-stream'})
        assert exchange.status_code == 200
        cookie = exchange.headers['set-cookie']
        assert '__Secure-atom_preview_20000=' in cookie
        assert 'httponly' in cookie.lower() and 'secure' in cookie.lower()
        assert client.post('/_atom/exchange', content=grant.secret,
                           headers={'Origin': 'https://192.0.2.10:20000',
                                    'Content-Type': 'application/octet-stream'}).status_code == 404
        view_path = exchange.json()['path']
        page = client.get(view_path)
        assert page.status_code == 200 and page.content == b'<html>heat</html>'
        assert page.headers['x-atom-revision'] == revision
        assert page.headers['cross-origin-opener-policy'] == 'same-origin'
        assert client.get('http://192.0.2.10:20000/',
                          headers={'Cookie': cookie.split(';', 1)[0]}).status_code == 404
        assert client.get('https://192.0.2.10:20001/').status_code == 404
        assert client.get('https://192.0.2.11:20000/').status_code == 404
        assert client.get('/_atom/private.js').status_code == 404
        AccessRepository(path).revoke_console_session(user_id='user', session_id=source.id)
        assert client.get(view_path).status_code == 404


def test_preview_process_refuses_old_schema_and_relative_paths(legacy, tmp_path):
    path, _ = legacy
    for version in range(11, 18):
        migrate(path, tmp_path / f'before-v{version}.db', target_version=version)
    config = IpPreviewConfig(path, tmp_path / 'artifacts', '192.0.2.10', 20000, 20003)
    with pytest.raises(PreviewStartupError, match='preview_startup_unavailable'):
        create_ip_preview_app(config)
    with pytest.raises(PreviewStartupError, match='preview_configuration_invalid'):
        create_ip_preview_app(IpPreviewConfig(Path('relative.db'), tmp_path / 'artifacts',
                                              '192.0.2.10', 20000, 20003))
