import sqlite3
import pytest

from app.migrations import migrate, verify, verify_backup, MigrationError
from app.migrations import contract_history_v19
from test_revision_migrations import legacy


@pytest.fixture
def v18(legacy, tmp_path):
    path, _ = legacy
    for version in range(11, 19):
        migrate(path, tmp_path / f'before-{version}.db', target_version=version)
    return path


def test_v19_backup_additive_replay_integrity(v18, tmp_path):
    backup = tmp_path / 'v18.db'
    result = migrate(v18, backup, target_version=19)
    assert result.version == verify(v18) == 19
    assert result.backup_sha256 == verify_backup(backup, expected_version=18)
    assert not migrate(v18, tmp_path / 'unused.db', target_version=19).applied
    with sqlite3.connect(v18) as db:
        assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert db.execute('SELECT count(*) FROM contract_snapshots').fetchone() == (0,)


def test_v19_failure_restores_exact_predecessor(v18, tmp_path, monkeypatch):
    original = contract_history_v19.apply
    def fail(db):
        original(db)
        raise sqlite3.OperationalError('injected migration failure')
    monkeypatch.setattr(contract_history_v19, 'apply', fail)
    backup = tmp_path / 'v18.db'
    with pytest.raises(MigrationError):
        migrate(v18, backup, target_version=19)
    assert verify(v18) == 18
    verify_backup(backup, expected_version=18)


def test_forward_candidate_migration_keeps_source_backup_and_rejects_downgrade(v18, tmp_path):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'deploy'))
    import forward_schema
    forward_schema.migrate_candidate(v18, target=19)
    assert verify(v18) == forward_schema.version(v18) == 19
    assert verify(v18.parent / 'before-contract-v19.db') == 18
    forward_schema.migrate_candidate(v18, target=19)
    with pytest.raises(ValueError, match='unsupported_forward_schema_transition'):
        forward_schema.migrate_candidate(v18, target=18)
