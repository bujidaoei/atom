from dataclasses import replace
import json
import os
import subprocess
import time

import pytest

from app.sandbox.docker_driver import DockerDriver, DriverError, FileProfile
from app.sandbox.grants import Grant
from app.sandbox.registry import Registry


IMAGE = os.environ.get("ATOM_TEST_DOCKER_IMAGE")
pytestmark = pytest.mark.skipif(not IMAGE, reason="requires explicit pinned local Docker test image")


@pytest.fixture
def owned(tmp_path):
    registry = Registry(tmp_path / "driver.db")
    driver = DockerDriver(registry.broker_id, IMAGE)
    attempts = []

    def allocate(seconds=45):
        now = int(time.time())
        number = str(len(attempts))
        attempt = registry.admit(Grant(jti="g" + number, org="test", project="test", run="r" + number,
            attempt="a", fence=1, base_revision="a" * 64, iat=now, exp=now + seconds))
        attempts.append(attempt)
        return attempt

    yield driver, allocate
    # Test cleanup also handles a driver assertion failure. Only exact owned names/labels.
    for attempt in attempts:
        result = subprocess.run(["docker", "inspect", attempt.container_name], capture_output=True, timeout=15)
        if result.returncode == 0:
            record = json.loads(result.stdout)[0]
            assert record["Config"]["Labels"]["atom.broker"] == registry.broker_id
            subprocess.run(["docker", "rm", "--force", record["Id"]], check=True, capture_output=True, timeout=15)
    remaining = subprocess.run(["docker", "ps", "-aq", "--filter", f"label=atom.broker={registry.broker_id}"],
                               check=True, capture_output=True, timeout=15)
    assert not remaining.stdout.strip()


def execute(attempt, code):
    return subprocess.run(["docker", "exec", attempt.container_name, "/usr/local/bin/python3", "-c", code],
                          capture_output=True, timeout=15)


def test_real_profile_idempotency_and_confirmed_termination(owned, monkeypatch):
    driver, allocate = owned
    attempt = allocate()
    monkeypatch.setenv("ATOM_DRIVER_SYNTHETIC_SECRET", "not-for-worker")
    first = driver.ensure(attempt)
    assert driver.ensure(attempt).id == first.id
    checks = execute(attempt, """
import errno,json,os,pathlib,socket
assert os.getuid()==1000
assert 'ATOM_DRIVER_SYNTHETIC_SECRET' not in os.environ
assert not pathlib.Path('/var/run/docker.sock').exists()
pathlib.Path('/workspace/ok').write_text('preserved')
try:
 pathlib.Path('/etc/denied').write_text('x')
 raise AssertionError('root write allowed')
except OSError as e: assert e.errno in (errno.EROFS,errno.EACCES)
with socket.socket() as s:
 s.settimeout(1)
 try:
  s.connect(('198.18.0.1',443));raise AssertionError('network allowed')
 except OSError as e: assert e.errno==errno.ENETUNREACH
try:
 with open('/workspace/quota','wb') as f:
  for _ in range(65): f.write(b'x'*1024*1024)
 raise AssertionError('quota missing')
except OSError as e: assert e.errno==errno.ENOSPC
finally: pathlib.Path('/workspace/quota').unlink(missing_ok=True)
print('verified')
""")
    assert checks.returncode == 0, checks.stderr
    assert checks.stdout.strip() == b"verified"
    driver.terminate(attempt)
    assert driver.inspect(attempt) is None
    with pytest.raises(DriverError, match="container_missing"):
        driver.ensure(replace(attempt, state="ready"))
    with pytest.raises(DriverError, match="attempt_not_provisionable"):
        driver.ensure(replace(attempt, state="terminated"))
    driver.terminate(attempt)


def test_independent_deadline_and_peer_survival(owned):
    driver, allocate = owned
    peer, expiring = allocate(45), allocate(4)
    driver.ensure(peer)
    driver.ensure(expiring)
    deadline = time.monotonic() + 8
    state = driver.inspect(expiring)
    while state.running and time.monotonic() < deadline:
        time.sleep(0.1)
        state = driver.inspect(expiring)
    assert not state.running and state.exit_code == 0
    assert driver.inspect(peer).running
    # Deadline can pass between the initial time check and Docker inspection.
    # Both refusals are valid; neither may restart the expired worker.
    with pytest.raises(DriverError, match="^(invalid_deadline|container_not_running)$"):
        driver.ensure(expiring)
    assert not driver.inspect(expiring).running


def test_wrong_ownership_and_exited_container_never_restarted(owned):
    driver, allocate = owned
    attempt = allocate()
    state = driver.ensure(attempt)
    with pytest.raises(DriverError, match="ownership_mismatch"):
        driver.terminate(replace(attempt, grant_fingerprint="b" * 64))
    assert driver.inspect(attempt).running
    subprocess.run(["docker", "stop", "--time", "1", state.id], check=True, capture_output=True, timeout=10)
    with pytest.raises(DriverError, match="container_not_running"):
        driver.ensure(attempt)
    assert not driver.inspect(attempt).running


def test_real_pid_and_memory_limits_preserve_peer(owned):
    driver, allocate = owned
    attempt, peer = allocate(), allocate()
    driver.ensure(attempt)
    driver.ensure(peer)
    result = execute(attempt, """
import errno,subprocess
children=[]
try:
 for _ in range(100):
  children.append(subprocess.Popen(['/usr/local/bin/python3','-c','import time;time.sleep(10)']))
 raise AssertionError('PID limit missing')
except OSError as error:
 assert error.errno==errno.EAGAIN
finally:
 for child in children: child.terminate()
 for child in children: child.wait(timeout=3)
print('pids-bounded')
""")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == b"pids-bounded"
    cpu = execute(attempt, """
import time
def counters(): return dict(line.split() for line in open('/sys/fs/cgroup/cpu.stat'))
before=counters()
deadline=time.monotonic()+1.5
while time.monotonic()<deadline: pass
after=counters()
assert int(after['nr_throttled'])>int(before['nr_throttled'])
assert int(after['throttled_usec'])>int(before['throttled_usec'])
print('cpu-throttled')
""")
    assert cpu.returncode == 0, cpu.stderr
    assert cpu.stdout.strip() == b"cpu-throttled"
    oom = execute(attempt, "allocation=bytearray(512*1024*1024)")
    assert oom.returncode == 137
    counters = execute(attempt, "print(open('/sys/fs/cgroup/memory.events').read())")
    assert counters.returncode == 0
    values = dict(line.split() for line in counters.stdout.decode().splitlines() if line.strip())
    assert int(values['oom_kill']) >= 1
    assert driver.inspect(peer).running


def test_new_policy_cannot_adopt_but_can_terminate_old_owned_container(owned):
    driver, allocate = owned
    attempt = allocate()
    driver.ensure(attempt)
    changed = DockerDriver(driver.broker_id, IMAGE, profile=FileProfile(pids=32))
    with pytest.raises(DriverError, match="ownership_mismatch"):
        changed.ensure(attempt)
    changed.terminate(attempt)
    assert driver.inspect(attempt) is None
