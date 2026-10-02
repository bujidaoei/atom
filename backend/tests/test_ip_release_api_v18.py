"""Owner release API selects the stable public IP port under paired cutover."""
from fastapi.testclient import TestClient

from app.config import get_settings
from app.console_auth import proof_for_new_session
from app.migrations import migrate
from app.project_origins import ProjectOriginRepository
from app.routers import preview
from test_rollback_v14_api import _configured_api, http_history
from test_adoption_repository import prepared
from test_adoption_verification_repository import adopted
from test_revision_migrations import legacy
from test_v13_content_consumers import published
from test_verifier_authority import authorized


def test_ip_release_uses_reserved_public_origin_without_dns_or_required_check(
        http_history, tmp_path, monkeypatch):
    path, store, intent, _source, _displaced = http_history
    for version in range(14, 19):
        migrate(path, tmp_path / f'before-v{version}.db', target_version=version)
    app, token, engine = _configured_api(path, store, intent, tmp_path, monkeypatch)
    app.include_router(preview.router)
    monkeypatch.setenv('ATOM_CONSOLE_ORIGIN', 'https://192.0.2.10')
    monkeypatch.setenv('ATOM_CONSOLE_PROOF_REQUIRED', 'true')
    monkeypatch.setenv('ATOM_IP_PREVIEW_ENABLED', 'true')
    monkeypatch.setenv('ATOM_IP_PUBLIC_ENABLED', 'true')
    monkeypatch.setenv('ATOM_IP_PREVIEW_ADDRESS', '192.0.2.10')
    monkeypatch.setenv('ATOM_IP_PREVIEW_FIRST_PORT', '20000')
    monkeypatch.setenv('ATOM_IP_PREVIEW_LAST_PORT', '20003')
    monkeypatch.setenv('ATOM_PUBLICATION_VERIFICATION', 'advisory')
    monkeypatch.delenv('ATOM_CONTENT_HOST_SUFFIX')
    get_settings.cache_clear()
    try:
        proof = proof_for_new_session(token)
        inspect = {'x-atom-console-proof': proof,
                   'x-atom-intent': 'inspect-verified-release'}
        with TestClient(app, base_url='https://192.0.2.10',
                        cookies={'__Host-atom_console': token}) as client:
            route = '/api/projects/project/releases'
            assert client.get(route + '/current', headers=inspect).status_code == 503
            origins = ProjectOriginRepository(path, first_port=20000, last_port=20003)
            assert origins.reserve_existing()[0].public_port == 20001
            current = client.get(route + '/current', headers=inspect)
            assert current.status_code == 200, current.text
            assert current.json()['publication']['sharingUrl'] == 'https://192.0.2.10:20001/'
            assert client.get('/p/' + intent['slug'] + '/assets/app.js?q=1',
                              follow_redirects=False).headers['location'] == (
                                  'https://192.0.2.10:20001/assets/app.js?q=1')
            assert client.get('/p/unknown', follow_redirects=False).status_code == 404
            assert client.get('/preview/project/', headers=inspect).status_code == 404
            history = client.get(route + '/history', headers=inspect)
            assert history.status_code == 200, history.text
            assert all(item['previewUrl'] is None for item in history.json()['items'])
            publish = client.post(route, json={
                'releaseId': 'f' * 32, 'expectedRevision': intent['expected_revision'],
                'expectedGeneration': 2, 'audience': 'public', 'slug': intent['slug']},
                headers={'origin': 'https://192.0.2.10',
                         'x-atom-console-proof': proof,
                         'x-atom-intent': 'publish-verified-release'})
            assert publish.status_code == 200, publish.text
            after = client.get(route + '/current', headers=inspect).json()['publication']
            assert after['generation'] == 3
            assert after['sharingUrl'] == 'https://192.0.2.10:20001/'
            assert after['pinnedUrl'] == after['sharingUrl']
            withdrawn = client.post(route + '/' + 'f' * 32 + '/unpublish',
                json={'commandId': 'e' * 32, 'expectedGeneration': 3},
                headers={'origin': 'https://192.0.2.10',
                         'x-atom-console-proof': proof,
                         'x-atom-intent': 'unpublish-verified-release'})
            assert withdrawn.status_code == 200, withdrawn.text
            assert client.get('/p/' + intent['slug'], follow_redirects=False).status_code == 404
            assert client.get(route + '/current', headers=inspect).json()['publication']['sharingUrl'] is None
    finally:
        engine.dispose()
        get_settings.cache_clear()
