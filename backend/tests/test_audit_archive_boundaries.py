"""Evidence probes for archive design; no retention/archive implementation claim."""
import sqlite3

from app.access_repository import AccessRepository
from app.migrations import backup_database, migrate, verify, verify_backup
from test_revision_migrations import legacy


def test_schema_valid_raw_database_copy_can_omit_committed_wal_events(legacy, tmp_path):
    path, initial = legacy
    migrate(path, initial, target_version=7)
    repository = AccessRepository(path)
    with sqlite3.connect(path) as keeper:
        assert keeper.execute('PRAGMA journal_mode=WAL').fetchone() == ('wal',)
        keeper.execute('PRAGMA wal_autocheckpoint=0')
        assert keeper.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone() == (0, 0, 0)
        session = repository.create_console_session(user_id='user', lifetime_seconds=60)
        with sqlite3.connect(path) as source:
            source.row_factory = sqlite3.Row
            expected = [dict(row) for row in source.execute('SELECT * FROM security_audit_events ORDER BY sequence')]
        assert len(expected) == 1
        # Deliberately incorrect technique, isolated here to demonstrate the hazard.
        raw_copy = tmp_path/'unsafe-raw-copy.db'
        raw_copy.write_bytes(path.read_bytes())
        assert verify(raw_copy) == 7
        with sqlite3.connect(raw_copy) as copied:
            assert copied.execute('PRAGMA integrity_check').fetchone() == ('ok',)
            assert copied.execute('SELECT count(*) FROM security_audit_events').fetchone() == (0,)
        saved = tmp_path/'consistent-backup.db'
        result = backup_database(path, saved)
        assert result.version == 7 and verify_backup(saved, expected_version=7) == result.sha256
        restored = tmp_path/'restored.db'
        with sqlite3.connect(saved) as origin, sqlite3.connect(restored) as target:
            origin.backup(target)
        assert verify(restored) == 7
        assert AccessRepository(restored).console_session(user_id='user', session_id=session.id) == session
        with sqlite3.connect(restored) as restored_db:
            restored_db.row_factory = sqlite3.Row
            actual = [dict(row) for row in restored_db.execute('SELECT * FROM security_audit_events ORDER BY sequence')]
            assert actual == expected
            # A whole database backup is privileged recovery material, not scoped audit export.
            assert restored_db.execute("SELECT password_hash FROM users WHERE id='user'").fetchone()[0] == 'synthetic'


def test_held_audit_reader_prevents_complete_wal_checkpoint(legacy):
    path, initial = legacy
    migrate(path, initial, target_version=7)
    repository = AccessRepository(path)
    with sqlite3.connect(path) as reader, sqlite3.connect(path) as checkpointer:
        assert reader.execute('PRAGMA journal_mode=WAL').fetchone() == ('wal',)
        reader.execute('PRAGMA wal_autocheckpoint=0')
        assert reader.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone() == (0, 0, 0)
        reader.execute('BEGIN')
        assert reader.execute('SELECT count(*) FROM security_audit_events').fetchone() == (0,)
        repository.create_console_session(user_id='user', lifetime_seconds=60)
        busy, frames, checkpointed = checkpointer.execute('PRAGMA wal_checkpoint(PASSIVE)').fetchone()
        assert busy == 0 and frames > checkpointed
        assert reader.execute('SELECT count(*) FROM security_audit_events').fetchone() == (0,)
        reader.rollback()
        assert checkpointer.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone() == (0, 0, 0)
        assert reader.execute('SELECT count(*) FROM security_audit_events').fetchone() == (1,)
