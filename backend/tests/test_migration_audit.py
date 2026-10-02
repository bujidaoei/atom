"""Rehearsal auditor verifies the full predecessor chain and business counts."""
import sqlite3

import pytest

from app.migration_audit import audit
from app.migrations import MigrationError, migrate
from test_revision_migrations import legacy


def test_audit_accepts_real_schema_chain_and_detects_changed_business_rows(legacy, tmp_path):
    path, _store = legacy
    migrate(path, tmp_path / 'before-v10.db', target_version=10)
    for version in range(11, 19):
        migrate(path, tmp_path / f'before-v{version}.db', target_version=version)
    result = audit(path, tmp_path)
    assert result['version'] == 18
    assert result['predecessorVersions'] == list(range(11, 19))
    assert result['counts']['projects'] >= 1
    with sqlite3.connect(path) as db:
        columns = [row[1] for row in db.execute('PRAGMA table_info(projects)')]
        projection = ','.join("'audit-extra'" if name == 'id' else name for name in columns)
        db.execute(f'INSERT INTO projects SELECT {projection} FROM projects LIMIT 1')
    with pytest.raises(MigrationError, match='migration_business_counts_changed'):
        audit(path, tmp_path)


def test_audit_requires_every_predecessor(legacy, tmp_path):
    path, _store = legacy
    migrate(path, tmp_path / 'before-v10.db', target_version=10)
    for version in range(11, 19):
        migrate(path, tmp_path / f'before-v{version}.db', target_version=version)
    (tmp_path / 'before-v15.db').unlink()
    with pytest.raises(MigrationError):
        audit(path, tmp_path)
