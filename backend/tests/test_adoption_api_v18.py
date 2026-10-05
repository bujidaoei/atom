"""Revision-bound race adoption through the production-shaped owner route."""
import sqlite3

from fastapi.testclient import TestClient

from app.console_auth import proof_for_new_session
from app.config import get_settings
from app.migrations import migrate
from app.routers import adoptions
from test_rollback_v14_api import _configured_api, http_history
from test_adoption_repository import prepared
from test_adoption_verification_repository import adopted
from test_first_adoption_v18 import empty_main
from test_revision_migrations import legacy


def test_owner_adopts_exact_heat_without_publishing_and_replays(http_history, tmp_path, monkeypatch):
    path, store, intent, _source, _displaced = http_history
    for version in range(14, 19):
        migrate(path, tmp_path / f'before-adopt-v{version}.db', target_version=version)
    app, token, engine = _configured_api(path, store, intent, tmp_path, monkeypatch)
    app.include_router(adoptions.router, prefix='/api')
    monkeypatch.setenv('ATOM_CONSOLE_PROOF_REQUIRED', 'true')
    get_settings.cache_clear()
    command = {'commandId': 'f' * 32, 'sourceRevisionId': 'heat-root',
               'expectedMainRevisionId': intent['expected_revision']}
    url = '/api/projects/project/race/heat/adopt'
    headers = {'origin': 'https://console.example.org',
               'x-atom-intent': 'adopt-heat-revision',
               'x-atom-console-proof': proof_for_new_session(token)}
    try:
        with TestClient(app, base_url='https://console.example.org',
                        cookies={'__Host-atom_console': token}) as client:
            assert client.post(url, json=command, headers=headers | {
                'origin': 'https://foreign.invalid'}).status_code == 403
            assert client.post(url, json=command, headers=headers | {
                'x-atom-intent': 'wrong'}).status_code == 403
            assert client.post(url, json=command, headers={
                key: value for key, value in headers.items() if key != 'x-atom-console-proof'
            }).status_code == 401
            before = client.get('/api/projects/project/releases/current',
                headers={'x-atom-intent': 'inspect-verified-release',
                         'x-atom-console-proof': headers['x-atom-console-proof']}).json()
            result = client.post(url, json=command, headers=headers)
            assert result.status_code == 200, result.text
            receipt = result.json()
            assert receipt['commandId'] == command['commandId']
            assert receipt['sourceRevisionId'] == command['sourceRevisionId']
            assert receipt['revisionId'] not in (command['sourceRevisionId'],
                                                  command['expectedMainRevisionId'])
            assert client.post(url, json=command, headers=headers).json() == receipt
            assert client.post(url, json=command | {'commandId': 'e' * 32},
                               headers=headers).status_code == 409
            assert client.post(url, json=command | {'sourceRevisionId': 'wrong'},
                               headers=headers).status_code == 409
            assert client.get('/api/projects/project/releases/current',
                headers={'x-atom-intent': 'inspect-verified-release',
                         'x-atom-console-proof': headers['x-atom-console-proof']}).json() == before
        with sqlite3.connect(path) as db:
            assert db.execute('SELECT current_revision_id FROM revision_workspaces '
                              'WHERE project_id=? AND heat_id IS NULL',
                              ('project',)).fetchone() == (receipt['revisionId'],)
            assert db.execute('SELECT winner_heat_id FROM races WHERE id=?',
                              ('race',)).fetchone() == ('heat',)
            assert db.execute('SELECT count(*) FROM revision_adoptions WHERE id=?',
                              (command['commandId'],)).fetchone() == (1,)
            assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_owner_can_adopt_first_candidate_with_null_expected_head(empty_main, tmp_path, monkeypatch):
    path, _main, payload, artifact = empty_main
    from test_adoption_repository import Store
    intent = {'policy_digest': 'a' * 64, 'runner_version': 'browser-v1'}
    app, token, engine = _configured_api(path, Store(artifact.key, payload),
                                         intent, tmp_path, monkeypatch)
    app.include_router(adoptions.router, prefix='/api')
    monkeypatch.setenv('ATOM_CONSOLE_PROOF_REQUIRED', 'true')
    get_settings.cache_clear()
    try:
        with TestClient(app, base_url='https://console.example.org',
                        cookies={'__Host-atom_console': token}) as client:
            response = client.post('/api/projects/project/race/heat/adopt',
                json={'commandId': 'e' * 32, 'sourceRevisionId': 'heat-root',
                      'expectedMainRevisionId': None},
                headers={'origin': 'https://console.example.org',
                         'x-atom-intent': 'adopt-heat-revision',
                         'x-atom-console-proof': proof_for_new_session(token)})
            assert response.status_code == 200, response.text
            assert response.json()['revisionId']
    finally:
        engine.dispose()
        get_settings.cache_clear()
