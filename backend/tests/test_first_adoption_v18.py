"""An empty main workspace can adopt its first completed race candidate atomically."""
import sqlite3

import pytest

from app.adoption_repository import AdoptionError, AdoptionRepository
from app.migrations import migrate
from test_adoption_repository import Store, adopt, snapshot, state
from test_revision_migrations import legacy


@pytest.fixture
def empty_main(legacy, tmp_path):
    path, baseline = legacy
    migrate(path, baseline, target_version=11)
    payload, artifact = snapshot(b'<html>first candidate</html>')
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        main, = db.execute('SELECT id FROM revision_workspaces WHERE heat_id IS NULL').fetchone()
        heat, = db.execute('SELECT id FROM revision_workspaces WHERE heat_id IS NOT NULL').fetchone()
        db.execute('INSERT INTO revision_artifacts VALUES (?,?,?,1)',
                   (artifact.key, artifact.revision, artifact.size))
        db.execute("INSERT INTO revision_records VALUES ('heat-root',?,'project',NULL,?,?,NULL,1)",
                   (heat, artifact.key, artifact.revision))
        db.execute("UPDATE revision_workspaces SET current_revision_id='heat-root',generation=1 WHERE id=?", (heat,))
        db.execute("UPDATE races SET status='done' WHERE id='race'")
        db.execute("UPDATE race_heats SET status='done' WHERE id='heat'")
    for version in range(12, 19):
        migrate(path, tmp_path / f'empty-before-v{version}.db', target_version=version)
    return path, main, payload, artifact


def test_first_adoption_seeds_root_and_commits_provenance_atomically(empty_main):
    path, main, payload, artifact = empty_main
    receipt = adopt(AdoptionRepository(path), Store(artifact.key, payload),
                    expected_main_revision_id=None)
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        row = db.execute('SELECT parent_revision_id,artifact_key,adoption_id FROM revision_records '
                         'WHERE id=?', (receipt.revision_id,)).fetchone()
        assert row[1:] == (artifact.key, 'command')
        root = db.execute('SELECT parent_revision_id,artifact_key,adoption_id FROM revision_records '
                          'WHERE id=? AND workspace_id=?', (row[0], main)).fetchone()
        assert root == (None, artifact.key, None)
        assert db.execute('SELECT current_revision_id,generation FROM revision_workspaces '
                          'WHERE id=?', (main,)).fetchone() == (receipt.revision_id, 2)
        assert db.execute('SELECT winner_heat_id FROM races WHERE id=?', ('race',)).fetchone() == ('heat',)
        assert db.execute('SELECT count(*) FROM revision_outbox WHERE workspace_id=?',
                          (main,)).fetchone() == (2,)
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    assert adopt(AdoptionRepository(path), Store(artifact.key, b'corrupt'),
                 expected_main_revision_id=None) == receipt


def test_first_adoption_late_collision_rolls_back_seed_and_winner(empty_main, monkeypatch):
    path, main, payload, artifact = empty_main
    before = state(path)
    class Fixed:
        hex = 'collision'
    monkeypatch.setattr('app.adoption_repository.uuid.uuid4', lambda: Fixed())
    with pytest.raises(AdoptionError, match='adoption_conflict'):
        adopt(AdoptionRepository(path), Store(artifact.key, payload),
              expected_main_revision_id=None)
    assert state(path) == before
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM revision_records WHERE workspace_id=?',
                          (main,)).fetchone() == (0,)
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
