"""Owner release API selects the stable public IP port under paired cutover."""
import socket
from fastapi.testclient import TestClient

from app.config import get_settings
from app.console_auth import proof_for_new_session
from app.content_repository import ContentRepository
from app.content_service import ContentService
from app.migrations import migrate
from app.preview_access import PreviewAccessRepository
from app.preview_service import PreviewService
from app.project_origins import ProjectOriginRepository
from app.project_port_hosts import ProjectPortHosts
from app.project_public_hosts import ProjectPublicHosts
from app.routers import preview
from test_ip_preview_browser_v18 import _adjacent_listeners, _start, _tls_files
from test_rollback_v14_api import _configured_api, http_history
from test_adoption_repository import prepared
from test_adoption_verification_repository import adopted
from test_revision_migrations import legacy
from test_v13_content_consumers import published
from test_verifier_authority import authorized


def test_ip_release_uses_reserved_public_origin_without_dns_or_required_check(
        http_history, tmp_path, monkeypatch):
    path, store, intent, source, _displaced = http_history
    for version in range(14, 19):
        migrate(path, tmp_path / f'before-v{version}.db', target_version=version)
    app, token, engine = _configured_api(path, store, intent, tmp_path, monkeypatch)
    app.include_router(preview.router)
    listeners = _adjacent_listeners()
    preview_port = listeners[0].getsockname()[1]
    public_port = listeners[1].getsockname()[1]
    address = '127.0.0.1'
    key, cert = _tls_files(tmp_path)
    monkeypatch.setenv('ATOM_CONSOLE_ORIGIN', 'https://' + address)
    monkeypatch.setenv('ATOM_CONSOLE_PROOF_REQUIRED', 'true')
    monkeypatch.setenv('ATOM_IP_PREVIEW_ENABLED', 'true')
    monkeypatch.setenv('ATOM_IP_PUBLIC_ENABLED', 'true')
    monkeypatch.setenv('ATOM_IP_PREVIEW_ADDRESS', address)
    monkeypatch.setenv('ATOM_IP_PREVIEW_FIRST_PORT', str(preview_port))
    monkeypatch.setenv('ATOM_IP_PREVIEW_LAST_PORT', str(public_port))
    monkeypatch.setenv('ATOM_IP_INGRESS_CA_FILE', str(cert))
    monkeypatch.setenv('ATOM_PUBLICATION_VERIFICATION', 'advisory')
    monkeypatch.delenv('ATOM_CONTENT_HOST_SUFFIX')
    get_settings.cache_clear()
    services = []
    try:
        proof = proof_for_new_session(token)
        inspect = {'x-atom-console-proof': proof,
                   'x-atom-intent': 'inspect-verified-release'}
        with TestClient(app, base_url='https://' + address,
                        cookies={'__Host-atom_console': token}) as client:
            route = '/api/projects/project/releases'
            assert client.get(route + '/current', headers=inspect).status_code == 503
            origins = ProjectOriginRepository(path, first_port=preview_port, last_port=public_port)
            assert origins.reserve_existing()[0].public_port == public_port
            hosts = ProjectPortHosts(address, origins)
            services.append(_start(PreviewService(PreviewAccessRepository(path), store, hosts),
                                   listeners[0], key, cert))
            content = ContentRepository(path)
            services.append(_start(ContentService(content, store,
                ProjectPublicHosts(address, origins, content)), listeners[1], key, cert))
            public_url = hosts.origin(public_port) + '/'
            current = client.get(route + '/current', headers=inspect)
            assert current.status_code == 200, current.text
            assert current.json()['publication']['sharingUrl'] == public_url
            assert client.get('/p/' + intent['slug'] + '/assets/app.js?q=1',
                              follow_redirects=False).headers['location'] == (
                                  public_url + 'assets/app.js?q=1')
            assert client.get('/p/unknown', follow_redirects=False).status_code == 404
            assert client.get('/preview/project/', headers=inspect).status_code == 404
            history = client.get(route + '/history', headers=inspect)
            assert history.status_code == 200, history.text
            assert all(item['previewUrl'] is None for item in history.json()['items'])
            command = {
                'releaseId': 'f' * 32, 'expectedRevision': intent['expected_revision'],
                'expectedGeneration': 2, 'audience': 'public', 'slug': intent['slug']}
            headers = {'origin': 'https://' + address,
                         'x-atom-console-proof': proof,
                         'x-atom-intent': 'publish-verified-release'}
            publish = client.post(route, json=command, headers=headers)
            assert publish.status_code == 200, publish.text
            after = client.get(route + '/current', headers=inspect).json()['publication']
            assert after['generation'] == 3
            assert after['sharingUrl'] == public_url
            assert after['pinnedUrl'] == after['sharingUrl']
            services[1][0].should_exit = True
            services[1][1].join(timeout=15)
            assert not services[1][1].is_alive()
            replay = client.post(route, json=command, headers=headers)
            assert replay.status_code == 200 and replay.json()['generation'] == 3
            unavailable = client.post(route, json=command | {
                'releaseId':'a' * 32, 'expectedGeneration':3}, headers=headers)
            assert unavailable.status_code == 503
            assert client.get(route + '/current', headers=inspect).json()['publication']['generation'] == 3
            restore = client.post(route + '/' + 'f' * 32 + '/rollback', json={
                'commandId':'b' * 32, 'newReleaseId':'1' * 32,
                'sourceReleaseId':source.release_id,
                'expectedGeneration':3,
                'expectedRevision':intent['expected_revision']},
                headers={'origin':'https://' + address,
                         'x-atom-console-proof':proof,
                         'x-atom-intent':'rollback-verified-release'})
            assert restore.status_code == 503, restore.text
            assert client.get(route + '/current', headers=inspect).json()['publication']['generation'] == 3
            listeners[1].close()
            replacement = socket.socket()
            replacement.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            replacement.bind((address, public_port))
            replacement.listen(32)
            listeners[1] = replacement
            recovered_content = ContentRepository(path)
            services[1] = _start(ContentService(recovered_content, store,
                ProjectPublicHosts(address, origins, recovered_content)),
                replacement, key, cert)
            recovered = client.post(route, json=command | {
                'releaseId':'a' * 32, 'expectedGeneration':3}, headers=headers)
            assert recovered.status_code == 200 and recovered.json()['generation'] == 4
            withdrawn = client.post(route + '/' + 'a' * 32 + '/unpublish',
                json={'commandId': 'e' * 32, 'expectedGeneration': 4},
                headers={'origin': 'https://' + address,
                         'x-atom-console-proof': proof,
                         'x-atom-intent': 'unpublish-verified-release'})
            assert withdrawn.status_code == 200, withdrawn.text
            assert client.get('/p/' + intent['slug'], follow_redirects=False).status_code == 404
            assert client.get(route + '/current', headers=inspect).json()['publication']['sharingUrl'] is None
    finally:
        for server, thread in services:
            server.should_exit = True
            thread.join(timeout=15)
            assert not thread.is_alive()
        for listener in listeners:
            listener.close()
        engine.dispose()
        get_settings.cache_clear()
