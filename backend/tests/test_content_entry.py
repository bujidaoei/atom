"""The standalone content process cannot start on an implicit or old ledger."""
from pathlib import Path

import pytest

from app.content_entry import ContentProcessConfig, ContentStartupError, create_app
from test_revision_migrations import legacy


def test_content_process_requires_explicit_isolated_authorities(monkeypatch, tmp_path):
    for name in ('ATOM_CONTENT_DB_PATH', 'ATOM_CONTENT_ARTIFACT_DIR',
                 'ATOM_CONTENT_HOST_SUFFIX', 'ATOM_CONTENT_CONSOLE_ORIGIN'):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ContentStartupError, match='content_configuration_missing'):
        ContentProcessConfig.from_environment()
    with pytest.raises(ContentStartupError, match='content_absolute_paths_required'):
        ContentProcessConfig(Path('relative.db'), tmp_path, 'content.example.test',
                             'https://console.example.org')
    with pytest.raises(ContentStartupError, match='content_origin_configuration_invalid'):
        ContentProcessConfig(tmp_path / 'source.db', tmp_path,
                             'content.example.test', 'https://console.content.example.test')


def test_old_schema_cannot_start_content_process(legacy, tmp_path):
    path, _ = legacy
    config = ContentProcessConfig(path, tmp_path / 'artifacts',
                                  'content.example.test', 'https://console.example.org')
    with pytest.raises(ContentStartupError, match='content_verified_schema_required'):
        create_app(config)
    assert not config.artifacts.exists()
