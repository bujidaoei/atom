"""A signed legacy owner sees an honest disabled release state."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db import get_db
from app.migrations import migrate
from app.routers import releases, verifications
from app.security import issue_session
from test_revision_migrations import legacy


def test_legacy_owner_reads_disabled_release_without_origin_error(legacy, tmp_path, monkeypatch):
    path, _ = legacy
    migrate(path, tmp_path / 'before-v10.db', target_version=10)
    values = {
        'ATOM_ENVIRONMENT': 'production',
        'ATOM_SANDBOX_MODE': 'broker',
        'ATOM_SESSION_MODE': 'legacy',
        'ATOM_COOKIE_SECURE': 'true',
        'ATOM_SECRET': 'synthetic-console-secret-32-characters',
        'ATOM_RUNTIME_TOKEN': 'synthetic-runtime-token-32-characters',
        'ATOM_RUNTIME_URL': 'http://127.0.0.1:1',
        'ATOM_BROKER_ORIGIN': 'http://127.0.0.1:2',
        'ATOM_BROKER_ADMIN_TOKEN': 'synthetic-broker-admin-32-characters',
        'ATOM_BROKER_GRANT_KEY': 'synthetic-broker-grant-32-characters',
        'ATOM_COMPLETION_GRANT_KEY': 'synthetic-completion-grant-32-characters',
        'ATOM_DB_PATH': str(path),
        'ATOM_ARTIFACT_DIR': str(tmp_path / 'artifacts'),
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv('ATOM_CONSOLE_ORIGIN', raising=False)
    get_settings.cache_clear()
    engine = create_engine(f'sqlite:///{path}', connect_args={'check_same_thread': False})
    sessions = sessionmaker(bind=engine)
    app = FastAPI()
    app.include_router(releases.router, prefix='/api')
    app.include_router(verifications.router, prefix='/api')

    def database():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = database
    try:
        owner = {'Cookie': 'atom_session=' + issue_session('user')}
        anonymous = TestClient(app, base_url='https://159.75.231.98')
        for suffix, detail in (
            ('releases/current', '可信发布尚未启用'),
            ('verifications/latest', '验证服务尚未启用'),
        ):
            route = '/api/projects/project/' + suffix
            assert anonymous.get(route).status_code == 401
            response = anonymous.get(route, headers=owner)
            assert response.status_code == 404
            assert response.json()['detail'] == detail
    finally:
        engine.dispose()
        get_settings.cache_clear()
