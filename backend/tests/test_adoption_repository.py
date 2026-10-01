"""Fenced adoption ledger tests; production v10 remains deliberately unwired."""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import struct
import subprocess
import sys
import time

import pytest

from app.adoption_repository import AdoptionError, AdoptionRepository
from app.artifacts import Artifact
from app.migrations import migrate, verify
from test_revision_migrations import legacy


def snapshot(content: bytes) -> tuple[bytes, Artifact]:
    manifest = json.dumps({'version': 1, 'files': [{'path': 'index.html', 'size': len(content),
        'sha256': hashlib.sha256(content).hexdigest()}]}, sort_keys=True,
        separators=(',', ':')).encode()
    payload = b'ATOMSNAP1\n' + struct.pack('>I', len(manifest)) + manifest + content
    return payload, Artifact(hashlib.sha256(payload).hexdigest(), hashlib.sha256(manifest).hexdigest(), len(payload))


class Store:
    def __init__(self, key, payload, hook=None):
        self.key, self.payload, self.hook, self.reads = key, payload, hook, 0

    def read(self, key):
        assert key == self.key
        self.reads += 1
        if self.hook:
            self.hook()
        return self.payload


@pytest.fixture(params=[12, 13], ids=['schema-v12', 'schema-v13'])
def prepared(legacy, tmp_path, request):
    path, baseline = legacy
    migrate(path, baseline, target_version=11)
    _, main_artifact = snapshot(b'<html>main</html>')
    heat_payload, heat_artifact = snapshot(b'<html>heat</html>')
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        main, = db.execute('SELECT id FROM revision_workspaces WHERE heat_id IS NULL').fetchone()
        heat, = db.execute('SELECT id FROM revision_workspaces WHERE heat_id IS NOT NULL').fetchone()
        for artifact in (main_artifact, heat_artifact):
            db.execute('INSERT INTO revision_artifacts VALUES (?,?,?,1)',
                       (artifact.key, artifact.revision, artifact.size))
        db.execute("INSERT INTO revision_records VALUES ('main-root',?,'project',NULL,?,?,NULL,1)",
                   (main, main_artifact.key, main_artifact.revision))
        db.execute("INSERT INTO revision_records VALUES ('heat-root',?,'project',NULL,?,?,NULL,1)",
                   (heat, heat_artifact.key, heat_artifact.revision))
        db.execute("UPDATE revision_workspaces SET current_revision_id='main-root',generation=1 WHERE id=?", (main,))
        db.execute("UPDATE revision_workspaces SET current_revision_id='heat-root',generation=1 WHERE id=?", (heat,))
        db.execute("UPDATE races SET status='done' WHERE id='race'")
        db.execute("UPDATE race_heats SET status='done' WHERE id='heat'")
    migrate(path, tmp_path / 'before-v12.db', target_version=12)
    if request.param == 13:
        migrate(path, tmp_path / 'before-v13.db', target_version=13)
    return path, main, heat, heat_payload, heat_artifact


def adopt(repo, store, **changes):
    intent = dict(owner='user', project_id='project', heat_id='heat',
                  source_revision_id='heat-root', expected_main_revision_id='main-root',
                  command_id='command', store=store)
    intent.update(changes)
    return repo.adopt(**intent)


def state(path):
    with sqlite3.connect(path) as db:
        return (db.execute("SELECT current_revision_id,generation FROM revision_workspaces WHERE heat_id IS NULL").fetchone(),
                db.execute("SELECT winner_heat_id FROM races WHERE id='race'").fetchone(),
                db.execute('SELECT count(*) FROM revision_adoptions').fetchone(),
                db.execute('SELECT count(*) FROM revision_outbox').fetchone())


def test_adoption_atomically_advances_head_winner_and_exact_replay(prepared):
    path, main, _, payload, artifact = prepared
    repo = AdoptionRepository(path)
    store = Store(artifact.key, payload)
    receipt = adopt(repo, store)
    assert receipt.command_id == 'command' and receipt.project_id == 'project'
    assert receipt.source_revision_id == 'heat-root' and receipt.artifact == artifact
    assert state(path) == ((receipt.revision_id, 2), ('heat',), (1,), (1,))
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        row = db.execute('SELECT workspace_id,parent_revision_id,producing_attempt_id,adoption_id,artifact_key,snapshot_revision FROM revision_records WHERE id=?',
                         (receipt.revision_id,)).fetchone()
        assert row == (main, 'main-root', None, 'command', artifact.key, artifact.revision)
        assert db.execute("SELECT status FROM projects WHERE id='project'").fetchone() == ('ready',)
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        db.execute("UPDATE revision_workspaces SET current_revision_id=NULL WHERE heat_id='heat'")
    assert adopt(repo, Store(artifact.key, b'invalid')) == receipt
    assert store.reads == 1
    with pytest.raises(AdoptionError, match='adoption_conflict'):
        adopt(repo, store, source_revision_id='different')
    assert state(path)[2:] == ((1,), (1,))


@pytest.mark.parametrize('change', [dict(owner='foreign'), dict(project_id='foreign'),
    dict(heat_id='unknown'), dict(source_revision_id='other'), dict(expected_main_revision_id='other')])
def test_wrong_scope_or_fence_has_no_effect(prepared, change):
    path, _, _, payload, artifact = prepared
    before = state(path)
    with pytest.raises(AdoptionError):
        adopt(AdoptionRepository(path), Store(artifact.key, payload), **change)
    assert state(path) == before


def test_missing_or_substituted_artifact_and_source_change_have_no_effect(prepared):
    path, _, heat, payload, artifact = prepared
    repo = AdoptionRepository(path)
    before = state(path)
    with pytest.raises(AdoptionError, match='adoption_artifact_unavailable'):
        adopt(repo, Store(artifact.key, b'corrupt'))
    assert state(path) == before
    def change_source():
        with sqlite3.connect(path) as db:
            db.execute('UPDATE revision_workspaces SET current_revision_id=NULL,generation=generation+1 WHERE id=?', (heat,))
    with pytest.raises(AdoptionError, match='adoption_conflict'):
        adopt(repo, Store(artifact.key, payload, change_source))
    assert state(path) == before


def test_late_unique_failure_rolls_back_revision_head_and_winner(prepared, monkeypatch):
    path, main, _, payload, artifact = prepared
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO revision_outbox VALUES ('collision',?,'main-root','revision.registered',1,NULL)", (main,))
    before, version = state(path), verify(path)
    class Fixed:
        hex = 'collision'
    monkeypatch.setattr('app.adoption_repository.uuid.uuid4', lambda: Fixed())
    with pytest.raises(AdoptionError, match='adoption_conflict'):
        adopt(AdoptionRepository(path), Store(artifact.key, payload))
    assert state(path) == before
    assert verify(path) == version


def test_two_competing_adoptions_commit_only_one(prepared):
    path, _, _, payload, artifact = prepared
    repo = AdoptionRepository(path)
    def run(command):
        try:
            return adopt(repo, Store(artifact.key, payload), command_id=command)
        except AdoptionError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(run, ('first', 'second')))
    assert sum(not isinstance(item, str) for item in outcomes) == 1
    assert 'adoption_conflict' in outcomes
    assert state(path)[2:] == ((1,), (1,))


def test_same_command_concurrent_replay_returns_one_revision(prepared):
    path, _, _, payload, artifact = prepared
    repo = AdoptionRepository(path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(lambda _: adopt(repo, Store(artifact.key, payload)), range(2)))
    assert receipts[0] == receipts[1]
    assert state(path)[2:] == ((1,), (1,))


def test_generation_change_during_artifact_read_is_fenced(prepared):
    path, main, _, payload, artifact = prepared
    before = state(path)
    def change_generation():
        with sqlite3.connect(path) as db:
            db.execute('UPDATE revision_workspaces SET generation=generation+1 WHERE id=?', (main,))
    with pytest.raises(AdoptionError, match='adoption_conflict'):
        adopt(AdoptionRepository(path), Store(artifact.key, payload, change_generation))
    assert state(path)[1:] == before[1:]


def test_busy_writer_is_bounded_and_has_no_effect(prepared):
    path, _, _, payload, artifact = prepared
    before = state(path)
    with sqlite3.connect(path) as writer:
        writer.execute('BEGIN IMMEDIATE')
        with pytest.raises(AdoptionError, match='adoption_unavailable'):
            adopt(AdoptionRepository(path, lock_timeout=0.05), Store(artifact.key, payload))
        writer.rollback()
    assert state(path) == before


def test_process_death_after_evidence_and_revision_insert_rolls_back(prepared):
    path, _, _, payload, artifact = prepared
    before, version = state(path), verify(path)
    script = '''import base64,os,sys
from pathlib import Path
import app.adoption_repository as module
from app.adoption_repository import AdoptionRepository
real=module.uuid.uuid4
calls=0
def crash():
    global calls
    calls+=1
    if calls==2:os._exit(49)
    return real()
module.uuid.uuid4=crash
class Store:
    def read(self,key):return base64.b64decode(sys.argv[2])
AdoptionRepository(Path(sys.argv[1])).adopt(owner='user',project_id='project',heat_id='heat',source_revision_id='heat-root',expected_main_revision_id='main-root',command_id='command',store=Store())
'''
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    result = subprocess.run([sys.executable, '-c', script, str(path),
        base64.b64encode(payload).decode()], env=env, capture_output=True, timeout=30)
    assert result.returncode == 49, result.stderr
    assert state(path) == before and verify(path) == version
    assert adopt(AdoptionRepository(path), Store(artifact.key, payload)).revision_id


def test_process_death_after_winner_update_rolls_back_all(prepared):
    path, _, _, payload, _ = prepared
    before, version = state(path), verify(path)
    script = '''import base64,os,sqlite3,sys
from pathlib import Path
import app.adoption_repository as module
real=sqlite3.connect
class CrashConnection(sqlite3.Connection):
    def execute(self,sql,parameters=()):
        result=super().execute(sql,parameters)
        if sql.startswith("UPDATE projects SET status='ready'"):os._exit(50)
        return result
def connect(*args,**kwargs):
    kwargs['factory']=CrashConnection
    return real(*args,**kwargs)
module.sqlite3.connect=connect
class Store:
    def read(self,key):return base64.b64decode(sys.argv[2])
module.AdoptionRepository(Path(sys.argv[1])).adopt(owner='user',project_id='project',heat_id='heat',source_revision_id='heat-root',expected_main_revision_id='main-root',command_id='command',store=Store())
'''
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    result = subprocess.run([sys.executable, '-c', script, str(path),
        base64.b64encode(payload).decode()], env=env, capture_output=True, timeout=30)
    assert result.returncode == 50, result.stderr
    assert state(path) == before and verify(path) == version


def test_execution_continues_from_adopted_main_revision(prepared):
    from app.revisions import RevisionRepository
    path, main, _, payload, artifact = prepared
    adopted = adopt(AdoptionRepository(path), Store(artifact.key, payload))
    with sqlite3.connect(path) as db:
        db.execute("UPDATE projects SET active_run_id='run' WHERE id='project'")
    revisions = RevisionRepository(path)
    assert revisions.current_revision('user', main).revision_id == adopted.revision_id
    attempt = revisions.reserve('user', main, 'run', 'attempt-after-adopt',
                                'grant-after-adopt', int(time.time()) + 120)
    assert attempt.base_revision_id == adopted.revision_id
    revisions.bind('user', 'attempt-after-adopt', 'broker-after-adopt')
    receipt = revisions.register('user', 'attempt-after-adopt', 'broker-after-adopt',
                                 'grant-after-adopt', artifact)
    assert revisions.current_revision('user', main).revision_id == receipt.revision_id
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT parent_revision_id,producing_attempt_id,adoption_id FROM revision_records WHERE id=?',
                          (receipt.revision_id,)).fetchone() == (adopted.revision_id, 'attempt-after-adopt', None)
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
