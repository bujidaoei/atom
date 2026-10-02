from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import os
import secrets
import socket
import sqlite3
import subprocess
import threading
import time

import pytest
import httpx
import uvicorn
from fastapi.testclient import TestClient

from app.sandbox.config import BrokerConfig
from app.sandbox.docker_driver import DockerDriver
from app.sandbox.grants import Grant, GrantCodec
from app.sandbox.registry import Registry
from app.sandbox.service import create_app

IMAGE = os.environ.get("ATOM_TEST_DOCKER_IMAGE")
pytestmark = pytest.mark.skipif(not IMAGE, reason="requires explicit pinned local Docker test image")


@pytest.fixture
def environment(tmp_path):
    config = BrokerConfig(tmp_path / "broker.db", IMAGE, secrets.token_urlsafe(32), secrets.token_urlsafe(32), sweep_seconds=1)
    now = int(time.time())
    grant = Grant("grant", "org", "project", "run", "attempt", 1, "a" * 64, now, now + 60)
    return config, grant, GrantCodec(config.grant_key.encode()), {"authorization": "Bearer " + config.admin_token}


def test_actual_http_admission_denials_revoke_and_shutdown(environment, monkeypatch):
    config, grant, codec, headers = environment
    app = create_app(config)
    with TestClient(app) as client:
        registry = Registry(config.registry_path)
        driver = DockerDriver(registry.broker_id, IMAGE)
        assert client.get("/ready", headers=headers).status_code == 200
        commands = []
        original_run = DockerDriver._run
        def observed_run(self, *arguments):
            commands.append(arguments[:2])
            return original_run(self, *arguments)
        monkeypatch.setattr(DockerDriver, "_run", observed_run)
        for token in ("invalid", codec.issue(grant) + "corruption"):
            assert client.post("/v1/admin/provision", json={"grant": token}, headers=headers).status_code == 403
        assert client.post("/v1/admin/provision", json={"grant": codec.issue(grant)}).status_code == 401
        assert registry.unterminated() == [] and driver.owned_inventory() == []
        assert not any(command in commands for command in (("container", "create"), ("container", "start"), ("container", "rm")))
        response = client.post("/v1/admin/provision", json={"grant": codec.issue(grant)}, headers=headers)
        assert response.status_code == 202 and response.json()["state"] == "provisioning"
        attempt = registry.find(response.json()["attempt_id"])
        assert driver.inspect(attempt).running
        duplicate = client.post("/v1/admin/provision", json={"grant": codec.issue(grant)}, headers=headers)
        assert duplicate.json()["attempt_id"] == attempt.id
        revoked = client.post("/v1/admin/revoke", json={"grant_id": grant.jti}, headers=headers)
        assert revoked.status_code == 200 and revoked.json()["state"] == "terminated"
        assert driver.inspect(attempt) is None
        # Revocation persists before the control lock. A concurrent sweep may
        # conservatively observe its pending intent; let the next sweep confirm.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and client.get("/ready", headers=headers).status_code != 200:
            time.sleep(0.1)
        assert client.post("/v1/admin/provision", json={"grant": codec.issue(grant)}, headers=headers).status_code == 409
        successor = replace(grant, jti="next", attempt="next", fence=2)
        response = client.post("/v1/admin/provision", json={"grant": codec.issue(successor)}, headers=headers)
        assert response.status_code == 202
        last = registry.find(response.json()["attempt_id"])
    assert registry.find(last.id).state == "terminated"
    assert driver.owned_inventory() == []


def test_cloned_registry_cannot_reap_source_attempt_while_source_broker_runs(environment, tmp_path):
    config, grant, codec, headers = environment
    with TestClient(create_app(config)) as source:
        response = source.post("/v1/admin/provision", json={"grant": codec.issue(grant)}, headers=headers)
        assert response.status_code == 202
        attempt = Registry(config.registry_path).find(response.json()["attempt_id"])
        driver = DockerDriver(Registry(config.registry_path).broker_id, IMAGE)
        assert driver.inspect(attempt).running
        clone_path = tmp_path / "clone" / "registry.db"
        clone_path.parent.mkdir()
        with sqlite3.connect(config.registry_path) as original, sqlite3.connect(clone_path) as clone:
            original.backup(clone)
        clone_config = replace(config, registry_path=clone_path)
        with TestClient(create_app(clone_config)) as copied:
            assert copied.get("/ready", headers=headers).status_code == 503
            assert copied.post("/v1/admin/provision", json={"grant": codec.issue(grant)},
                               headers=headers).status_code == 503
            assert source.get("/ready", headers=headers).status_code == 200
            assert driver.inspect(attempt).running
            assert Registry(config.registry_path).find(attempt.id).state == "provisioning"
        revoked = source.post("/v1/admin/revoke", json={"grant_id": grant.jti}, headers=headers)
        assert revoked.status_code == 200
        assert driver.inspect(attempt) is None


def test_lost_daemon_lease_fails_closed_without_new_container(environment):
    config, grant, codec, headers = environment
    with TestClient(create_app(config)) as client:
        registry = Registry(config.registry_path)
        lease_name = "atom-broker-lease-" + registry.broker_id
        assert client.get("/ready", headers=headers).status_code == 200
        subprocess.run(["docker", "container", "rm", "--force", lease_name],
                       check=True, capture_output=True, timeout=10)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and client.get("/ready", headers=headers).status_code == 200:
            time.sleep(0.1)
        assert client.get("/ready", headers=headers).status_code == 503
        assert client.post("/v1/admin/provision", json={"grant": codec.issue(grant)},
                           headers=headers).status_code == 503
        assert registry.unterminated() == []


def test_scheduled_expiry_without_explicit_sweep(environment):
    config, grant, codec, headers = environment
    grant = replace(grant, exp=int(time.time()) + 4)
    with TestClient(create_app(config)) as client:
        response = client.post("/v1/admin/provision", json={"grant": codec.issue(grant)}, headers=headers)
        assert response.status_code == 202
        registry = Registry(config.registry_path)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and registry.find(response.json()["attempt_id"]).state != "terminated":
            time.sleep(0.1)
        assert registry.find(response.json()["attempt_id"]).state == "terminated"
        assert DockerDriver(registry.broker_id, IMAGE).owned_inventory() == []


def test_startup_daemon_failure_retries_to_ready(environment, monkeypatch):
    config, grant, codec, headers = environment
    with monkeypatch.context() as changed:
        changed.setenv("DOCKER_HOST", "tcp://127.0.0.1:1")
        changed.delenv("DOCKER_CONTEXT", raising=False)
        changed.delenv("DOCKER_TLS_VERIFY", raising=False)
        with TestClient(create_app(config)) as client:
            assert client.get("/ready", headers=headers).status_code == 503
            assert client.post("/v1/admin/provision", json={"grant": codec.issue(grant)}, headers=headers).status_code == 503
            changed.undo()
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and client.get("/ready", headers=headers).status_code != 200:
                time.sleep(0.1)
            assert client.get("/ready", headers=headers).status_code == 200


def test_actual_loopback_http_transport_and_shutdown(environment):
    config, grant, codec, headers = environment
    app = create_app(config)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level="critical", proxy_headers=False, limit_concurrency=32))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not server.started and thread.is_alive():
            time.sleep(0.05)
        assert server.started
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10, trust_env=False) as client:
            assert client.get("/health").status_code == 401
            response = client.post("/v1/admin/provision", json={"grant": codec.issue(grant)}, headers=headers)
            assert response.status_code == 202
            registry = Registry(config.registry_path)
            attempt = registry.find(response.json()["attempt_id"])
            assert DockerDriver(registry.broker_id, IMAGE).inspect(attempt).running
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        listener.close()
    assert not thread.is_alive()
    assert registry.find(attempt.id).state == "terminated"
    assert DockerDriver(registry.broker_id, IMAGE).owned_inventory() == []


def test_missing_pinned_image_prevents_readiness_and_creation(environment):
    config, grant, codec, headers = environment
    config = replace(config, image="sha256:" + "0" * 64)
    with TestClient(create_app(config)) as client:
        assert client.get("/ready", headers=headers).status_code == 503
        assert client.post("/v1/admin/provision", json={"grant": codec.issue(grant)}, headers=headers).status_code == 503
        registry = Registry(config.registry_path)
        assert registry.unterminated() == []
        assert DockerDriver(registry.broker_id, IMAGE).owned_inventory() == []


def test_ready_waits_for_real_reconciliation_before_reporting_state(environment, monkeypatch):
    config, _, _, headers = environment
    app = create_app(replace(config, sweep_seconds=60))
    with TestClient(app) as client:
        lifecycle = app.state.lifecycle
        assert client.get("/ready", headers=headers).status_code == 200
        entered = threading.Event()
        release = threading.Event()
        inventory = lifecycle.driver.owned_inventory

        def held_inventory():
            entered.set()
            if not release.wait(5):
                raise AssertionError("reconciliation was not released")
            return inventory()

        monkeypatch.setattr(lifecycle.driver, "owned_inventory", held_inventory)
        with ThreadPoolExecutor(max_workers=2) as pool:
            sweep = pool.submit(lifecycle.sweep)
            try:
                assert entered.wait(5)
                assert not lifecycle.ready
                probe = pool.submit(client.get, "/ready", headers=headers)
                time.sleep(0.1)
                assert not probe.done()
            finally:
                release.set()
            sweep.result(timeout=10)
            response = probe.result(timeout=5)
            assert response.status_code == 200
            assert response.json() == {"alive": True, "ready": True}
