"""Protected migrations operate on a SQLite copy and retain predecessor backups."""
import sqlite3

from app.migrations import migrate, verify, verify_backup
from app.publication_rehearsal import rehearse
from test_revision_migrations import legacy


def test_schema10_to17_rehearsal_preserves_source_and_every_backup(legacy, tmp_path):
    path, _ = legacy
    for version in range(1, 11):
        migrate(path, tmp_path / f'init-before-{version}.db', target_version=version)
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA journal_mode=WAL').fetchone() == ('wal',)
    before = path.read_bytes()
    destination = tmp_path / 'rehearsal'
    receipt = rehearse(path, destination)
    assert receipt.source_version == verify(path) == 10
    assert receipt.final_version == verify(destination / 'atom.db') == 17
    assert receipt.projects == 1 and receipt.publication_rows == 0
    assert receipt.predecessor_backups == 7
    for version in range(11, 18):
        assert verify_backup(destination / f'before-v{version}.db',
                             expected_version=version - 1)
    with sqlite3.connect(destination / 'atom.db') as db:
        assert db.execute('PRAGMA journal_mode').fetchone() == ('delete',)
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    assert path.read_bytes() == before
