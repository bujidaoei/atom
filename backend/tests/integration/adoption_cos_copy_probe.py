"""Opt-in read-only live-data capture and COS-backed adoption on a disposable copy.

Run inside an exact API container with ATOM_ADOPTION_PROBE_PROJECT set. The source
database is opened read-only; only a temporary SQLite backup is changed.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
import uuid

from app.artifacts import configured_artifact_store
from app.config import get_settings


def _rows_digest(db, table, project_id):
    rows = db.execute(f'SELECT * FROM {table} WHERE project_id=? ORDER BY rowid',
                      (project_id,)).fetchall()
    return hashlib.sha256(repr(rows).encode()).hexdigest()


def main():
    project_id = os.environ['ATOM_ADOPTION_PROBE_PROJECT']
    if len(project_id) != 32 or any(c not in '0123456789abcdef' for c in project_id):
        raise RuntimeError('invalid_probe_project')
    module_path = os.environ.get('ATOM_ADOPTION_PROBE_MODULE')
    if module_path:
        spec = importlib.util.spec_from_file_location('app.adoption_repository', module_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        repository_type = module.AdoptionRepository
    else:
        from app.adoption_repository import AdoptionRepository
        repository_type = AdoptionRepository
    settings = get_settings()
    if settings.storage_backend != 'cos' or settings.sandbox_mode != 'broker':
        raise RuntimeError('production_cos_required')
    source = sqlite3.connect(settings.db_path.as_uri() + '?mode=ro', uri=True)
    source.execute('PRAGMA query_only=ON')
    try:
        with TemporaryDirectory(prefix='atom-adoption-copy-') as directory:
            destination = Path(directory) / 'copy.db'
            copy = sqlite3.connect(destination)
            try:
                source.backup(copy)
            finally:
                copy.close()
            os.chmod(destination, 0o600)
            with sqlite3.connect(destination) as db:
                candidate = db.execute('''SELECT p.user_id,h.id,h.status,r.status,
                    source.current_revision_id,target.current_revision_id
                    FROM projects p JOIN races r ON r.project_id=p.id
                    JOIN race_heats h ON h.race_id=r.id
                    JOIN revision_workspaces source ON source.project_id=p.id AND source.heat_id=h.id
                    JOIN revision_workspaces target ON target.project_id=p.id AND target.heat_id IS NULL
                    WHERE p.id=? AND h.status='done' AND r.status='done'
                      AND source.current_revision_id IS NOT NULL
                    ORDER BY h.id LIMIT 1''', (project_id,)).fetchone()
                if candidate is None:
                    raise RuntimeError('no_completed_saved_heat')
                owner, heat_id, _heat_status, _race_status, heat_revision, main_revision = candidate
                before = tuple(_rows_digest(db, table, project_id) for table in
                               ('release_publications', 'release_records'))
            store = configured_artifact_store(settings, settings.artifact_dir)
            receipt = repository_type(destination).adopt(
                owner=owner, project_id=project_id, heat_id=heat_id,
                source_revision_id=heat_revision,
                expected_main_revision_id=main_revision,
                command_id=uuid.uuid4().hex, store=store)
            with sqlite3.connect(destination) as db:
                assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)
                assert db.execute('PRAGMA foreign_key_check').fetchall() == []
                assert db.execute('SELECT current_revision_id FROM revision_workspaces '
                                  'WHERE project_id=? AND heat_id IS NULL',
                                  (project_id,)).fetchone() == (receipt.revision_id,)
                assert before == tuple(_rows_digest(db, table, project_id) for table in
                                       ('release_publications', 'release_records'))
            live = source.execute('SELECT current_revision_id FROM revision_workspaces '
                                  'WHERE project_id=? AND heat_id IS NULL',
                                  (project_id,)).fetchone()
            assert live == (main_revision,)
            print(json.dumps({'status': 'cos_copy_adoption_verified',
                              'firstAdoption': main_revision is None,
                              'publicationUnchanged': True,
                              'liveSourceUnchanged': True}))
    finally:
        source.close()


if __name__ == '__main__':
    main()
