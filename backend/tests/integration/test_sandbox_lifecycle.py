from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from app.sandbox.docker_driver import DockerDriver, DriverError
from app.sandbox.grants import Grant
from app.sandbox.lifecycle import Lifecycle, LifecycleError
from app.sandbox.registry import Registry, RegistryError


IMAGE = os.environ.get("ATOM_TEST_DOCKER_IMAGE")
pytestmark = pytest.mark.skipif(not IMAGE, reason="requires explicit pinned local Docker test image")


@pytest.fixture
def environment(tmp_path):
    registry = Registry(tmp_path / "broker.db")
    driver = DockerDriver(registry.broker_id, IMAGE)
    now = int(time.time())
    grant = Grant(jti="grant", org="org", project="project", run="run", attempt="a", fence=1,
                  base_revision="a" * 64, iat=now, exp=now + 90)
    yield registry, driver, grant
    for attempt in registry.unterminated():
        driver.terminate(attempt)
    remaining = driver.owned_inventory()
    assert not remaining


def test_real_duplicate_provision_revoke_and_process_lease(environment):
    registry, driver, grant = environment
    with Lifecycle(registry, driver) as lifecycle:
        assert not lifecycle.ready
        lifecycle.start()
        assert lifecycle.ready
        with pytest.raises(LifecycleError, match="broker_already_owned"):
            Lifecycle(Registry(registry.path), driver)
        first = lifecycle.provision(grant)
        assert first.state == "provisioning"
        original = driver.inspect(first).id
        lifecycle.start()
        assert driver.inspect(first).id == original
        assert lifecycle.provision(grant).id == first.id
        assert driver.inspect(first).id == original
        stopped = lifecycle.revoke(grant.jti)
        assert stopped.state == "terminated"
        assert driver.inspect(first) is None
        with pytest.raises(RegistryError, match="grant_revoked"):
            lifecycle.provision(grant)


def test_abrupt_coordinator_exit_retires_old_worker(environment):
    registry, driver, grant = environment
    script = """
import json,os,sys
from pathlib import Path
from app.sandbox.registry import Registry
from app.sandbox.docker_driver import DockerDriver
from app.sandbox.grants import Grant
from app.sandbox.lifecycle import Lifecycle
r=Registry(Path(sys.argv[1]));d=DockerDriver(r.broker_id,sys.argv[2]);l=Lifecycle(r,d)
l.start();a=l.provision(Grant(**json.loads(sys.stdin.read())))
print(a.id,flush=True);os._exit(23)
"""
    child = subprocess.run([sys.executable, "-c", script, str(registry.path), IMAGE],
        input=json.dumps(asdict(grant)), text=True, capture_output=True, timeout=30,
        cwd=Path(__file__).resolve().parents[2])
    assert child.returncode == 23, child.stderr
    attempt = registry.find(child.stdout.strip())
    assert driver.inspect(attempt).running
    with Lifecycle(Registry(registry.path), driver) as restarted:
        restarted.start()
        assert restarted.ready
        assert registry.find(attempt.id).state == "terminated"
        assert driver.inspect(attempt) is None
        with pytest.raises(RegistryError, match="grant_revoked"):
            restarted.provision(grant)
        new = restarted.provision(replace(grant, jti="next", attempt="b", fence=2))
        assert new.id != attempt.id


def test_response_lost_after_real_creation_is_cleaned(environment):
    registry, driver, grant = environment

    class LostResponse(DockerDriver):
        def ensure(self, attempt):
            super().ensure(attempt)
            raise DriverError("driver_timeout")

    with Lifecycle(registry, LostResponse(registry.broker_id, IMAGE)) as lifecycle:
        lifecycle.start()
        with pytest.raises(LifecycleError, match="provision_failed"):
            lifecycle.provision(grant)
        assert registry.find_grant(grant.jti).state == "terminated"
        assert not driver.owned_inventory()


def test_unreachable_daemon_keeps_unknown_and_blocks_dispatch(environment, monkeypatch):
    registry, driver, grant = environment
    with Lifecycle(registry, driver) as lifecycle:
        lifecycle.start()
        attempt = lifecycle.provision(grant)
        # Reach an actual closed local endpoint; never stop the user's Docker daemon.
        with monkeypatch.context() as changed:
            changed.setenv("DOCKER_HOST", "tcp://127.0.0.1:1")
            changed.delenv("DOCKER_CONTEXT", raising=False)
            changed.delenv("DOCKER_TLS_VERIFY", raising=False)
            with pytest.raises(LifecycleError, match="termination_unknown"):
                lifecycle.revoke(grant.jti)
            assert registry.find(attempt.id).state == "termination_unknown"
            assert not lifecycle.ready
            with pytest.raises(LifecycleError, match="broker_not_ready"):
                lifecycle.provision(replace(grant, jti="next", attempt="b", fence=2))
        assert driver.inspect(attempt).running
        lifecycle.sweep()
        assert lifecycle.ready
        assert registry.find(attempt.id).state == "terminated"
        assert driver.inspect(attempt) is None


def test_unrecorded_owned_container_blocks_readiness_without_deletion(environment):
    registry, driver, grant = environment
    with Lifecycle(registry, driver) as lifecycle:
        lifecycle.start()
        registered = lifecycle.provision(grant)
        # A real extra container models a lost registry record. No untrusted owner is touched.
        orphan_id = "e" * 32
        orphan = replace(registered, id=orphan_id,
                         container_name=f"atom-sbox-{registry.broker_id[:12]}-{orphan_id}")
        driver.ensure(orphan)
        try:
            with pytest.raises(LifecycleError, match="orphan_recovery_required"):
                lifecycle.sweep()
            assert not lifecycle.ready
            assert driver.inspect(orphan).running
        finally:
            driver.terminate(orphan)
        lifecycle.sweep()
        assert lifecycle.ready


def test_expiry_sweep_retires_attempt_and_preserves_peer(environment):
    registry, driver, grant = environment
    with Lifecycle(registry, driver) as lifecycle:
        lifecycle.start()
        peer = lifecycle.provision(grant)
        short = replace(grant, jti="short", run="short", exp=int(time.time()) + 4)
        expiring = lifecycle.provision(short)
        while time.time() < short.exp:
            time.sleep(0.05)
        lifecycle.sweep()
        assert lifecycle.ready
        assert registry.find(expiring.id).state == "terminated"
        assert driver.inspect(expiring) is None
        assert driver.inspect(peer).running
