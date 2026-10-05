"""Console issuance uses the same real revision and port ledger as serving."""
from types import SimpleNamespace
import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.access_repository import AccessRepository
from app.bounded_operations import BoundedOperations
from app.deps import owned_project
from app.migrations import migrate
from app.preview_access import PreviewAccessRepository
from app.project_origins import ProjectOriginRepository
from app.routers import preview_access as issuer
from test_adoption_repository import prepared
from test_adoption_verification_repository import adopted
from test_revision_migrations import legacy
from test_rollback_v14_repository import historical
from test_v13_content_consumers import published
from test_verifier_authority import authorized


def test_preview_issuer_requires_switch_intent_owner_and_reserved_port(historical, tmp_path,
                                                                        monkeypatch):
    path, _store, _intent, _source, _displaced = historical
    for version in range(15, 19):
        migrate(path, tmp_path / f'before-v{version}.db', target_version=version)
    with sqlite3.connect(path) as db:
        revision = db.execute('SELECT revision_id FROM release_records WHERE project_id=? LIMIT 1',
                              ('project',)).fetchone()[0]
    source = AccessRepository(path).create_console_session(user_id='user', lifetime_seconds=900)
    settings = SimpleNamespace(ip_preview_enabled=False, db_path=path,
        ip_preview_first_port=20000, ip_preview_last_port=20003,
        ip_preview_address='192.0.2.10')
    monkeypatch.setattr(issuer, 'get_settings', lambda: settings)
    monkeypatch.setattr(issuer, 'request_session_token', lambda _request: 'token')
    monkeypatch.setattr(issuer, 'credentials', lambda: SimpleNamespace(
        authenticate=lambda _token: SimpleNamespace(id=source.id, user_id='user')))

    def same_origin(request):
        if (request.url.scheme != 'https' or request.headers.get('host') != '192.0.2.10'
                or request.headers.get('origin') != 'https://192.0.2.10'):
            issuer._deny(403)

    monkeypatch.setattr(issuer, 'require_auth_origin', same_origin)
    app = FastAPI()
    app.state.content_issuer = BoundedOperations()
    app.dependency_overrides[owned_project] = lambda: SimpleNamespace(id='project', user_id='user')
    app.include_router(issuer.router, prefix='/api')
    body = {'revisionId': revision}
    intent = {'Origin': 'https://192.0.2.10', 'x-atom-intent': 'open-revision-preview'}
    with TestClient(app, base_url='https://192.0.2.10') as client:
        route = '/api/projects/project/preview-access'
        assert client.post(route, json=body, headers=intent).status_code == 404
        settings.ip_preview_enabled = True
        assert client.post(route, json=body, headers=intent).status_code == 404
        assert client.post(route, json=body, headers={'Origin': 'https://192.0.2.10'}).status_code == 403
        ProjectOriginRepository(path, first_port=20000, last_port=20003).reserve('project')
        assert client.post(route, json=body, headers={**intent, 'Origin': 'https://evil.test'}).status_code == 403
        assert client.post(route, json={'revisionId': 'other'}, headers=intent).status_code == 404
        response = client.post(route, json=body, headers=intent)
        assert response.status_code == 200
        assert response.json()['url'].startswith('https://192.0.2.10:20000/_atom/open#')
        assert response.headers['cache-control'] == 'no-store'
        assert app.state.content_issuer.pending_count == 0
        handoff = response.json()['url'].partition('#')[2]
        session = PreviewAccessRepository(path).exchange(project_id='project', handoff=handoff)
        assert session.revision_id == revision
