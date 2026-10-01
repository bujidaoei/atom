import multiprocessing
import os
import subprocess
import time
import uuid

import pytest

from app.sandbox.daemon_lease import BrokerDaemonLease, DaemonLeaseError


IMAGE = os.environ.get("ATOM_TEST_DOCKER_IMAGE")
pytestmark = pytest.mark.skipif(not IMAGE, reason="requires explicit pinned local Docker image")


def _inventory(identity):
    name = "atom-broker-lease-" + identity
    result = subprocess.run(
        ["docker", "container", "ls", "--all", "--filter", "name=^/" + name + "$",
         "--format", "{{.Names}}"], capture_output=True, text=True, check=True, timeout=5)
    return result.stdout.splitlines()


def _hold(identity, ready):
    lease = BrokerDaemonLease(identity, IMAGE)
    lease.acquire()
    ready.set()
    time.sleep(30)


def test_same_daemon_clone_cannot_acquire_or_remove_source_lease():
    identity = uuid.uuid4().hex
    first = BrokerDaemonLease(identity, IMAGE)
    second = BrokerDaemonLease(identity, IMAGE)
    try:
        first.acquire()
        assert first.alive and _inventory(identity) == [first.name]
        with pytest.raises(DaemonLeaseError, match="^broker_identity_in_use$"):
            second.acquire()
        assert first.alive and _inventory(identity) == [first.name]
    finally:
        second.close()
        first.close()
    assert _inventory(identity) == []
    second.acquire()
    try:
        assert second.alive and _inventory(identity) == [second.name]
    finally:
        second.close()
    assert _inventory(identity) == []


@pytest.mark.skipif(os.name == "nt", reason="SIGKILL process death requires Linux")
def test_owner_process_death_releases_daemon_identity():
    identity = uuid.uuid4().hex
    ready = multiprocessing.Event()
    process = multiprocessing.Process(target=_hold, args=(identity, ready))
    process.start()
    try:
        assert ready.wait(15)
        assert _inventory(identity) == ["atom-broker-lease-" + identity]
        process.kill()
        process.join(timeout=5)
        assert process.exitcode is not None
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and _inventory(identity):
            time.sleep(0.1)
        assert _inventory(identity) == []
    finally:
        if process.is_alive():
            process.kill()
            process.join(timeout=5)
        subprocess.run(["docker", "container", "rm", "--force", "atom-broker-lease-" + identity],
                       capture_output=True, timeout=5)
