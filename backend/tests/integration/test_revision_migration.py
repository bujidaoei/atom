import json
import os
from pathlib import Path
import sqlite3
import time

import pytest
from sqlalchemy import create_engine

from app.models import Base
from app.sandbox.docker_driver import DockerDriver, run_bounded
from app.sandbox.grants import Grant
from app.sandbox.lifecycle import Lifecycle
from app.sandbox.registry import Registry

IMAGE = os.environ.get("ATOM_TEST_DOCKER_IMAGE")
pytestmark = pytest.mark.skipif(not IMAGE, reason="requires explicit pinned local Docker test image")


def test_actual_linux_migration_backup_restore_and_crash(tmp_path):
    root = Path(__file__).resolve().parents[3]
    baseline = tmp_path / "baseline.db"
    engine = create_engine("sqlite:///" + baseline.as_posix())
    Base.metadata.create_all(engine)
    engine.dispose()
    with sqlite3.connect(baseline) as db:
        schema = "\n".join(db.iterdump())
    payload = json.dumps({
        "schema": schema,
        "revision_v1": (root / "backend/app/migrations/revision_v1.py").read_text(encoding="utf-8"),
        "release_v2": (root / "backend/app/migrations/release_v2.py").read_text(encoding="utf-8"),
        "migration": (root / "backend/app/migrations/__init__.py").read_text(encoding="utf-8"),
    }).encode()
    script = '''
import json,os,sqlite3,sys,types
from pathlib import Path
sources=json.loads(sys.stdin.buffer.read())
app=types.ModuleType('app');app.__path__=[];sys.modules['app']=app
m=types.ModuleType('app.migrations');m.__path__=[];m.__package__=m.__name__;sys.modules[m.__name__]=m
v=types.ModuleType('app.migrations.revision_v1');sys.modules[v.__name__]=v
exec(compile(sources['revision_v1'],'revision_v1.py','exec'),v.__dict__)
v2=types.ModuleType('app.migrations.release_v2');v2.__package__='app.migrations';sys.modules[v2.__name__]=v2
exec(compile(sources['release_v2'],'release_v2.py','exec'),v2.__dict__)
exec(compile(sources['migration'],'migration.py','exec'),m.__dict__)
source=Path('/workspace/api.db'); backup=Path('/workspace/backup.db')
with sqlite3.connect(source) as db:
    db.executescript(sources['schema'])
    db.execute('PRAGMA journal_mode=WAL')
pid=os.fork()
if pid==0:
    original=m._apply_revision_schema
    def crash(db):
        original(db)
        os._exit(41)
    m._apply_revision_schema=crash
    m.migrate(source,backup)
    os._exit(1)
assert os.waitpid(pid,0)[1]==41<<8
assert m.verify(source)==0 and m.verify_backup(backup)
assert backup.stat().st_mode & 0o777 == 0o600
assert m.migrate(source,Path('/workspace/retry.db')).applied
assert m.verify(source)==1
versioned=Path('/workspace/versioned.db')
result=m.backup_database(source,versioned)
assert result.version==1 and m.verify_backup(versioned,expected_version=1)==result.sha256
assert versioned.stat().st_mode & 0o777 == 0o600
with sqlite3.connect(versioned) as src, sqlite3.connect('/workspace/versioned-restored.db') as dst:
    src.backup(dst)
assert m.verify(Path('/workspace/versioned-restored.db'))==1
pid=os.fork()
if pid==0:
    original=v2.apply
    def crash_release(db):
        original(db)
        os._exit(42)
    v2.apply=crash_release
    m.migrate(source,Path('/workspace/before-release.db'),target_version=2)
    os._exit(1)
assert os.waitpid(pid,0)[1]==42<<8
assert m.verify(source)==1 and m.verify_backup(Path('/workspace/before-release.db'),expected_version=1)
assert m.migrate(source,Path('/workspace/retry-release.db'),target_version=2).applied
assert m.verify(source)==2
saved=m.backup_database(source,Path('/workspace/release-backup.db'))
assert saved.version==2 and m.verify_backup(Path('/workspace/release-backup.db'),expected_version=2)==saved.sha256
restored=Path('/workspace/restored.db')
with sqlite3.connect(backup) as src, sqlite3.connect(restored) as dst:
    src.backup(dst)
assert m.verify(restored)==0
assert m.migrate(restored,Path('/workspace/restored-backup.db')).applied
print('linux-migration-restored')
'''
    registry = Registry(tmp_path / "broker.db")
    driver = DockerDriver(registry.broker_id, IMAGE)
    now = int(time.time())
    grant = Grant("g", "o", "p", "r", "a", 1, "a" * 64, now, now + 120)
    with Lifecycle(registry, driver) as lifecycle:
        lifecycle.start()
        state = driver.inspect(lifecycle.provision(grant))
        status, out, err = run_bounded([driver.executable, "exec", "-i", state.id, "python3", "-I", "-c", script],
                                       input_data=payload, timeout=25)
        assert status == 0, err.decode("utf-8")
        assert out.strip() == b"linux-migration-restored"
    assert not driver.owned_inventory()
