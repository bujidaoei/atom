import json
import os
from pathlib import Path

import pytest

from app.audit_archive import encode_archive
from app.sandbox.audit_recovery import AuditRecoveryOperations
from app.sandbox.docker_driver import DockerDriver, DriverError, run_bounded
from app.sandbox.lifecycle import Lifecycle
from app.sandbox.registry import Registry
from test_retention_plan import planned, reader, audited_release, release, ledger, legacy

IMAGE = os.environ.get('ATOM_TEST_DOCKER_IMAGE')
pytestmark = pytest.mark.skipif(not IMAGE,reason='requires explicit pinned sandbox image')


@pytest.mark.parametrize('fault',[None,'exit','output','timeout'])
def test_fixed_worker_full_restore_source_denial_and_confirmed_cleanup(planned,tmp_path,monkeypatch,fault):
    source, repo = planned
    plan = repo.plan(policy_id='policy',expected_generation=1)
    policy = plan['context']['policy']
    archive = encode_archive(events=[row['event'] for row in plan['items']],context_sha256=plan['context_sha256'],
        plan_sha256=plan['plan_sha256'],scope_kind=policy['scope_kind'],scope_id=policy['scope_id'],
        event_kind=policy['event_kind'],after=0,upper_sequence=plan['upper_sequence'])
    registry = Registry(tmp_path/'broker.db')
    driver = DockerDriver(registry.broker_id,IMAGE)
    observed = []
    original = AuditRecoveryOperations.execute
    def execute(self,attempt,payload,**kwargs):
        state = driver.inspect(attempt)
        status,metadata,err = run_bounded([driver.executable,'inspect',state.id])
        assert status == 0,err.decode()
        configuration = json.loads(metadata)[0]
        assert all(mount['Type'] == 'tmpfs' for mount in configuration['Mounts'])
        assert configuration['HostConfig']['NetworkMode'] == 'none'
        assert configuration['HostConfig']['ReadonlyRootfs']
        # Actual worker: prove host source and control sockets are absent, root cannot be written,
        # and no inherited open descriptor points at source/store. Never mount the source for this test.
        script = '''
import json,os
from pathlib import Path
assert not Path('/var/run/docker.sock').exists()
assert not Path('/tmp/source.db').exists()
assert not Path('/store').exists()
assert not Path(SOURCE_PATH).exists()
try:
    Path('/source-authority-probe').write_text('denied')
except PermissionError:pass
except OSError as error:assert error.errno==30
else:raise AssertionError('root writable')
descriptors=[]
for path in Path('/proc/self/fd').iterdir():
    try:descriptors.append(os.readlink(path))
    except FileNotFoundError:pass
assert not any('source.db' in item or '/store/' in item for item in descriptors)
print(json.dumps({'uid':os.getuid(),'denied':True}))
'''.replace('SOURCE_PATH',repr(str(source)))
        status,out,err = run_bounded([driver.executable,'exec',state.id,'python3','-I','-c',script])
        assert status == 0,err.decode()
        assert json.loads(out) == {'uid':1000,'denied':True}
        observed.append(state.id)
        return original(self,attempt,payload,**kwargs)
    # Fixture time is100/200; actual Docker deadlines must use actual host time.
    import time
    monkeypatch.setattr(time,'time',lambda: time.time_ns()/1e9)
    monkeypatch.setattr(AuditRecoveryOperations,'execute',execute)
    if fault:
        program = {'exit':'raise SystemExit(2)','output':"import sys;sys.stdout.write('x'*263169);sys.stdout.flush()",
                   'timeout':'import time;time.sleep(30)'}[fault]
        monkeypatch.setattr('app.sandbox.audit_recovery._PROGRAM',program)
    with Lifecycle(registry,driver) as lifecycle:
        lifecycle.start()
        if fault:
            with pytest.raises(DriverError):
                lifecycle.verify_audit_archive(archive.payload,expected_sha256=archive.sha256)
        else:
            result = lifecycle.verify_audit_archive(archive.payload,expected_sha256=archive.sha256)
            assert result['protocol'] == 'audit-recovery-v2' and result['image'] == IMAGE
            assert result['result']['events'] == [row['event'] for row in plan['items']]
        assert observed and not driver.owned_inventory()
    assert not driver.owned_inventory()
