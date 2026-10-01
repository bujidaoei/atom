"""Real Linux archive persistence across writer removal; explicit pinned image required."""
import json
import os
from pathlib import Path
import uuid

import pytest

from app.sandbox.docker_driver import run_bounded

IMAGE = os.environ.get('ATOM_TEST_API_IMAGE')
pytestmark = pytest.mark.skipif(not IMAGE, reason='requires explicit pinned local API image')


def test_archive_survives_writer_removal():
    backend = Path(__file__).resolve().parents[2]
    owner = uuid.uuid4().hex
    volume = 'atom-audit-archive-test-'+owner
    label = 'atom.audit-archive-test='+owner
    containers = []
    status, _, err = run_bounded(['docker','volume','create','--label',label,volume])
    assert status == 0, err.decode()

    def remove(name):
        status, out, err = run_bounded(['docker','inspect',name])
        assert status == 0, err.decode()
        state = json.loads(out)[0]
        assert state['Config']['Labels']['atom.audit-archive-test'] == owner
        status, _, err = run_bounded(['docker','rm','--force',state['Id']])
        assert status == 0, err.decode()
        containers.remove(name)

    def execute(script, setup=False):
        name = 'atom-audit-archive-test-'+uuid.uuid4().hex
        containers.append(name)
        command = ['docker','run','--name',name,'--label',label,'--network=none','--read-only',
            '--cap-drop=ALL','--security-opt=no-new-privileges','--user','0:0' if setup else '1000:1000',
            '--tmpfs','/tmp:rw,nosuid,nodev,size=32m','--mount',f'type=volume,source={volume},target=/store',
            '--mount',f'type=bind,source={backend},target=/src,readonly','--workdir','/src','--env','PYTHONPATH=/src']
        if setup: command += ['--cap-add=CHOWN']
        status, out, err = run_bounded([*command,'--entrypoint','python',IMAGE,'-B','-c',script], timeout=25)
        assert status == 0, err.decode()
        remove(name)
        return out

    script = """
import runpy
from pathlib import Path
from app.audit_archive_store import AuditArchiveStore
from app.audit_archive import recover_archive
test = runpy.run_path('/src/tests/test_audit_archive_store.py')['ArchiveStoreTests']()
test.setUp()
archive = test.archive
store = AuditArchiveStore(Path('/store'))
"""
    try:
        execute("import os;os.chmod('/store',0o700);os.chown('/store',1000,1000)", setup=True)
        written = execute(script+"print(store.put(archive.payload,expected_sha256=archive.sha256).sha256)")
        restored = execute(script+"payload=store.read(expected_sha256=archive.sha256);assert payload==archive.payload;result=recover_archive(payload,expected_sha256=archive.sha256);assert len(result['events'])==1;print(result['archive_sha256'])")
        assert restored == written
    finally:
        for name in list(containers): remove(name)
        status, out, err = run_bounded(['docker','volume','inspect',volume])
        assert status == 0, err.decode()
        assert json.loads(out)[0]['Labels']['atom.audit-archive-test'] == owner
        status, _, err = run_bounded(['docker','volume','rm',volume])
        assert status == 0, err.decode()
