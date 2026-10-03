"""Authenticated advisory delivery works without a configured verifier."""
import sqlite3

from fastapi.testclient import TestClient
import pytest

from app.config import get_settings
from app.migrations import migrate
from app.release_history import publication_history
from app.verification_repository import VerificationError
from test_revision_migrations import legacy
from test_adoption_repository import prepared
from test_adoption_verification_repository import adopted
from test_rollback_v14_api import http_history, _configured_api


def test_advisory_http_without_verifier_and_strict_policy_cannot_be_bypassed(http_history, tmp_path, monkeypatch):
    path, store, intent, _source, displaced = http_history
    for version in (14, 15, 16):
        migrate(path, tmp_path / f'before-{version}.db', target_version=version)
    app, token, engine = _configured_api(path, store, intent, tmp_path, monkeypatch)
    monkeypatch.setenv('ATOM_PUBLICATION_VERIFICATION', 'advisory')
    verifier = {name: getattr(get_settings(), name) for name in
                ('verifier_origin', 'verifier_control_token', 'verifier_policy_digest', 'verifier_runner_version')}
    for name in verifier:
        monkeypatch.delenv('ATOM_' + name.upper())
    get_settings.cache_clear()
    route = '/api/projects/project/releases'
    body = {'releaseId': 'e' * 32, 'expectedRevision': intent['expected_revision'],
            'expectedGeneration': 2, 'audience': 'public', 'slug': intent['slug']}
    headers = {'origin': 'https://console.example.org', 'x-atom-intent': 'publish-verified-release'}
    try:
        with TestClient(app, base_url='https://console.example.org',
                        cookies={'__Host-atom_console': token}) as client:
            response = client.post(route, json=body, headers=headers)
            assert response.status_code == 200, response.text
            assert response.json()['generation'] == 3
            assert client.post(route, json=body, headers=headers).json() == response.json()
            current = client.get(route + '/current', headers={'x-atom-intent': 'inspect-verified-release'})
            assert current.status_code == 200
            assert current.json()['publication']['verificationId'] is None
            assert current.json()['publication']['verificationMode'] == 'advisory'
            assert client.post(route, json=body, headers=headers | {'origin': 'https://foreign.invalid'}).status_code == 403
            withdrawn = client.post(route + '/' + body['releaseId'] + '/unpublish',
                json={'commandId': '1' * 32, 'expectedGeneration': 3},
                headers=headers | {'x-atom-intent': 'unpublish-verified-release'})
            assert withdrawn.status_code == 200, withdrawn.text
            restored = client.post(route + '/' + body['releaseId'] + '/rollback',
                json={'commandId': '2' * 32, 'newReleaseId': '3' * 32,
                      'sourceReleaseId': body['releaseId'], 'expectedGeneration': 4,
                      'expectedRevision': intent['expected_revision']},
                headers=headers | {'x-atom-intent': 'rollback-verified-release'})
            assert restored.status_code == 200, restored.text
            assert restored.json()['generation'] == 5
            inspect = {'x-atom-intent': 'inspect-verified-release'}
            history = client.get(route + '/history?limit=1', headers=inspect)
            assert history.status_code == 200, history.text
            assert history.json()['publicationPolicy'] == 'advisory'
            assert len(history.json()['items']) == 1 and history.json()['nextCursor']
            observed = history.json()['items']
            cursor = history.json()['nextCursor']
            while cursor:
                page = client.get(route + '/history', params={'limit': 1, 'cursor': cursor}, headers=inspect)
                assert page.status_code == 200
                observed.extend(page.json()['items'])
                cursor = page.json()['nextCursor']
            assert len(observed) == len({row['releaseId'] for row in observed}) == 4
            live = [row for row in observed if row['isLive']]
            assert len(live) == 1 and live[0]['releaseId'] == '3' * 32
            assert live[0]['restoredFrom'] == body['releaseId']
            for query in ('limit=0', 'limit=51', 'limit=2&limit=3', 'cursor=bad', 'unexpected=1'):
                assert client.get(route + '/history?' + query, headers=inspect).status_code == 400
            assert client.get(route + '/history', headers=inspect | {'origin': 'https://foreign.invalid'}).status_code == 400
            with pytest.raises(VerificationError, match='release_not_found'):
                publication_history(path, owner='foreign', project_id='project')
            for name, value in verifier.items():
                monkeypatch.setenv('ATOM_' + name.upper(), value)
            monkeypatch.setenv('ATOM_PUBLICATION_VERIFICATION', 'required')
            get_settings.cache_clear()
            assert client.post(route, json=body | {'expectedGeneration': 3}, headers=headers).status_code == 400
            assert client.post(route, json=body | {'verificationMode': 'advisory'}, headers=headers).status_code == 400
        with TestClient(app, base_url='https://console.example.org') as anonymous:
            assert anonymous.post(route, json=body, headers=headers).status_code == 401
        with sqlite3.connect(path) as db:
            assert db.execute('SELECT release_id,generation FROM release_publications').fetchone() == ('3' * 32, 5)
    finally:
        engine.dispose()
        get_settings.cache_clear()
