import asyncio
from dataclasses import replace
import hashlib
import json
import os
import secrets
import socket
import struct
import threading
import time
import subprocess
from pathlib import Path

import httpx
import pytest
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
    config = BrokerConfig(tmp_path / "broker.db", IMAGE, secrets.token_urlsafe(32), secrets.token_urlsafe(32), sweep_seconds=60)
    manifest = b'{"files":[],"version":1}'
    archive = b"ATOMSNAP1\n" + struct.pack(">I", len(manifest)) + manifest
    now = int(time.time())
    grant = Grant("g", "o", "p", "r", "a", 1, hashlib.sha256(manifest).hexdigest(), now, now + 180)
    token = GrantCodec(config.grant_key.encode()).issue(grant)
    return config, grant, token, archive


def initialize(client, config, token, archive):
    admin = {"authorization": "Bearer " + config.admin_token}
    created = client.post("/v1/admin/provision", json={"grant": token}, headers=admin)
    assert created.status_code == 202, created.text
    seeded = client.post("/v1/admin/seed", content=archive,
                         headers={**admin, "x-atom-grant": token, "content-type": "application/octet-stream"})
    assert seeded.status_code == 200 and seeded.json()["state"] == "ready", seeded.text
    assert seeded.json()["attempt_id"] == created.json()["attempt_id"]
    return seeded.json()["attempt_id"]


def test_actual_checkpoint_http_boundary_and_exact_confirmation(environment):
    config, grant, token, archive = environment
    app = create_app(config)
    admin = {'authorization': 'Bearer ' + config.admin_token, 'x-atom-grant': token}
    export_url, confirm_url = '/v1/admin/checkpoints/export', '/v1/admin/checkpoints/confirm'
    with TestClient(app) as client:
        attempt = initialize(client, config, token, archive)
        body = {'attempt_id': attempt}
        assert client.post(export_url,json=body,headers={'authorization':'Bearer '+token}).status_code == 401
        assert client.post(export_url,json={'attempt_id':'f'*32},headers=admin).status_code == 409
        assert Registry(config.registry_path).find(attempt).state == 'ready'
        output = client.post(export_url,json=body,headers=admin)
        assert output.status_code == 200, output.text
        assert output.content == archive and output.headers['cache-control'] == 'no-store'
        assert output.headers['x-atom-artifact-key'] == hashlib.sha256(archive).hexdigest()
        assert output.headers['x-atom-revision'] == grant.base_revision
        assert client.post(export_url,json=body,headers=admin).content == output.content
        headers = {**admin,'content-type':'application/octet-stream','x-atom-attempt':attempt,
                   'x-atom-export-version':output.headers['x-atom-export-version'],
                   'x-atom-registered-revision':output.headers['x-atom-revision']}
        for changes in ({'x-atom-export-version':'01'},{'x-atom-export-version':'-1'},
                        {'x-atom-attempt':'f'*32},{'x-atom-registered-revision':'x'*64}):
            assert client.post(confirm_url,content=archive,headers={**headers,**changes}).status_code in (400,409)
        assert client.post(confirm_url,content=archive[:-1],headers=headers).status_code == 400
        assert Registry(config.registry_path).find(attempt).state == 'quiescing'
        first = client.post(confirm_url,content=archive,headers=headers)
        assert first.status_code == 200 and first.json()['state'] == 'checkpointed', first.text
        assert client.post(confirm_url,content=archive,headers=headers).json() == first.json()
        assert client.post(export_url,json=body,headers=admin).status_code == 409
        assert client.post('/v1/admin/revoke',json={'grant_id':grant.jti},headers=admin).status_code == 200
        assert client.post(confirm_url,content=archive,headers=headers).status_code == 409


def test_slow_export_holds_slot_but_revocation_remains_available(environment):
    config, grant, token, archive = environment
    app = create_app(config)
    async def scenario():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://broker') as client:
                admin = {'authorization':'Bearer '+config.admin_token}
                created = await client.post('/v1/admin/provision',json={'grant':token},headers=admin)
                attempt = created.json()['attempt_id']
                seeded = await client.post('/v1/admin/seed',content=archive,headers={**admin,
                    'x-atom-grant':token,'content-type':'application/octet-stream'})
                assert seeded.status_code == 200
                entered, release = asyncio.Event(), asyncio.Event()
                messages = []
                body = json.dumps({'attempt_id':attempt}).encode()
                async def receive():
                    return {'type':'http.request','body':body,'more_body':False}
                async def send(message):
                    messages.append(message)
                    if message['type'] == 'http.response.body':
                        entered.set()
                        await release.wait()
                headers = {**admin,'x-atom-grant':token,'content-type':'application/json'}
                scope = {'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST',
                    'scheme':'http','path':'/v1/admin/checkpoints/export','raw_path':b'/v1/admin/checkpoints/export',
                    'root_path':'','query_string':b'','headers':[(k.encode(),v.encode()) for k,v in headers.items()],
                    'client':('127.0.0.1',1),'server':('broker',80)}
                pending = asyncio.create_task(app(scope,receive,send))
                try:
                    await asyncio.wait_for(entered.wait(),10)
                    assert app.state.transfer_lock.locked()
                    async def unread():
                        raise AssertionError('busy body must not be read')
                        yield b''
                    busy = await client.post('/v1/admin/checkpoints/export',content=unread(),headers=headers)
                    assert busy.status_code == 503 and busy.json()['error'] == 'broker_busy'
                    revoked = await client.post('/v1/admin/revoke',json={'grant_id':grant.jti},headers=admin)
                    assert revoked.status_code == 200
                finally:
                    release.set()
                    await asyncio.wait_for(pending,10)
                assert not app.state.transfer_lock.locked()
                assert messages[-1]['body'] == archive
                assert app.state.lifecycle.registry.find(attempt).state == 'terminated'
    asyncio.run(scenario())


def test_real_seed_files_receipts_and_revocation_over_http(environment):
    config, grant, token, archive = environment
    with TestClient(create_app(config)) as client:
        attempt_id = initialize(client, config, token, archive)
        url = f"/v1/attempts/{attempt_id}/files"
        headers = {"authorization": "Bearer " + token}
        body = {"operation_id": "one", "tool_call_id": "tool:1", "operation": {"op": "write", "path": "a.txt", "content": "真实"}}
        first = client.post(url, json=body, headers=headers)
        assert first.status_code == 200 and first.json()["outcome"]["ok"]
        assert first.json()["tool_call_id"] == "tool:1"
        assert client.post(url, json=body, headers=headers).json() == first.json()
        conflict = {**body, "operation": {**body["operation"], "content": "changed"}}
        assert client.post(url, json=conflict, headers=headers).status_code == 409
        read = client.post(url, json={**body, "operation_id": "read", "operation": {"op": "read_bytes", "path": "a.txt"}}, headers=headers)
        assert read.json()["outcome"]["data"]["sha256"] == hashlib.sha256("真实".encode()).hexdigest()
        cas = client.post(url, json={**conflict, "operation_id": "cas", "operation": {**conflict["operation"], "expected_sha256": "f" * 64}}, headers=headers)
        assert cas.json()["outcome"] == {"ok": False, "error": "file_conflict"}
        assert client.post("/v1/admin/revoke", json={"grant_id": grant.jti}, headers={"authorization": "Bearer " + config.admin_token}).status_code == 200
        assert client.post(url, json=body, headers=headers).status_code == 409
        registry = Registry(config.registry_path)
        assert registry.find_operation(attempt_id, "one").state == "completed"
        assert DockerDriver(registry.broker_id, IMAGE).owned_inventory() == []


def test_denied_transfer_inputs_do_not_create_receipts_or_modify_worker(environment):
    config, grant, token, archive = environment
    with TestClient(create_app(config)) as client:
        attempt_id = initialize(client, config, token, archive)
        url = f"/v1/attempts/{attempt_id}/files"
        headers = {"authorization": "Bearer " + token, "content-type": "application/json"}
        body = {"operation_id": "bad", "tool_call_id": "tool", "operation": {"op": "write", "path": "a", "content": "data"}}
        for payload in ("[]", '{"operation_id":"bad","operation_id":"bad"}',
                        json.dumps({**body, "extra": True}), json.dumps({**body, "operation_id": True}),
                        json.dumps({**body, "operation": {**body["operation"], "content": "\ud800"}}),
                        json.dumps({**body, "operation": {**body["operation"], "path": "../outside"}})):
            assert client.post(url, content=payload, headers=headers).status_code == 400
        assert client.post(url, json=body, headers={"authorization": "Bearer " + config.admin_token}).status_code == 403
        assert client.post(url, json=body).status_code == 401
        assert client.post(url, json=body, headers=[("authorization", "Bearer " + token)] * 2).status_code == 401
        assert client.post("/v1/attempts/" + "f" * 32 + "/files", json=body, headers=headers).status_code == 409
        assert client.post(url, json=body, headers={**headers, "content-encoding": "gzip"}).status_code == 415
        assert client.post(url, content=b"x" * (50 * 1024 * 1024 + 1), headers=headers).status_code == 413
        registry = Registry(config.registry_path)
        assert registry.find_operation(attempt_id, "bad") is None
        listing = client.post(url, json={**body, "operation_id": "list", "operation": {"op": "glob", "pattern": "**", "limit": 10}}, headers=headers)
        assert listing.json()["outcome"]["data"]["text"] == "(no matches)"


def test_seed_denials_do_not_admit_or_execute(environment):
    config, grant, token, archive = environment
    admin = {"authorization": "Bearer " + config.admin_token}
    with TestClient(create_app(config)) as client:
        assert client.post("/v1/admin/seed", content=archive, headers={"authorization": "Bearer " + token}).status_code == 401
        assert client.post("/v1/admin/seed", content=archive, headers={**admin, "x-atom-grant": "invalid"}).status_code == 403
        assert client.post("/v1/admin/seed", content=archive, headers={**admin, "x-atom-grant": token}).status_code == 409
        assert Registry(config.registry_path).unterminated() == []
        created = client.post("/v1/admin/provision", json={"grant": token}, headers=admin)
        attempt_id = created.json()["attempt_id"]
        seed_headers = {**admin, "x-atom-grant": token, "content-type": "application/octet-stream"}
        oversized = client.post("/v1/admin/seed", content=b"x" * (65 * 1024 * 1024 + 15), headers=seed_headers)
        assert oversized.status_code == 413
        assert Registry(config.registry_path).find(attempt_id).state == "provisioning"
        assert client.post("/v1/admin/seed", content=archive, headers=seed_headers).status_code == 200


def test_real_loopback_seed_and_file_transport(environment):
    config, grant, token, archive = environment
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(create_app(config), log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        with httpx.Client(base_url=f"http://127.0.0.1:{listener.getsockname()[1]}", timeout=30, trust_env=False) as client:
            attempt_id = initialize(client, config, token, archive)
            result = client.post(f"/v1/attempts/{attempt_id}/files", headers={"authorization": "Bearer " + token},
                json={"operation_id": "write", "tool_call_id": "tool", "operation": {"op": "write", "path": "a", "content": "network"}})
            assert result.status_code == 200 and result.json()["outcome"]["data"]["bytes_written"] == 7
            exported = client.post('/v1/admin/checkpoints/export',json={'attempt_id':attempt_id},
                headers={'authorization':'Bearer '+config.admin_token,'x-atom-grant':token})
            assert exported.status_code == 200
            assert exported.headers['x-atom-artifact-key'] == hashlib.sha256(exported.content).hexdigest()
            assert exported.content.endswith(b'network')
            confirmed = client.post('/v1/admin/checkpoints/confirm',content=exported.content,headers={
                'authorization':'Bearer '+config.admin_token,'x-atom-grant':token,
                'content-type':'application/octet-stream','x-atom-attempt':attempt_id,
                'x-atom-export-version':exported.headers['x-atom-export-version'],
                'x-atom-registered-revision':exported.headers['x-atom-revision']})
            assert confirmed.status_code == 200 and confirmed.json()['state'] == 'checkpointed'
    finally:
        server.should_exit = True
        thread.join(timeout=20)
        listener.close()
    assert not thread.is_alive()
    registry = Registry(config.registry_path)
    assert DockerDriver(registry.broker_id, IMAGE).owned_inventory() == []


def test_busy_intake_rejects_second_body_and_revoke_stays_available(environment):
    config, grant, token, archive = environment
    app = create_app(config)
    async def scenario():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
                admin = {"authorization": "Bearer " + config.admin_token}
                created = await client.post("/v1/admin/provision", json={"grant": token}, headers=admin)
                attempt_id = created.json()["attempt_id"]
                seeded = await client.post("/v1/admin/seed", content=archive,
                    headers={**admin, "x-atom-grant": token, "content-type": "application/octet-stream"})
                assert seeded.status_code == 200
                url = f"/v1/attempts/{attempt_id}/files"
                headers = {"authorization": "Bearer " + token, "content-type": "application/json"}
                entered, release = asyncio.Event(), asyncio.Event()
                body = json.dumps({"operation_id": "held", "tool_call_id": "tool", "operation": {"op": "write", "path": "a", "content": "data"}}).encode()
                async def held_body():
                    yield body[:1]
                    entered.set()
                    await release.wait()
                    yield body[1:]
                async def forbidden_body():
                    raise AssertionError("busy request body must not be consumed")
                    yield b""
                pending = asyncio.create_task(client.post(url, content=held_body(), headers=headers))
                try:
                    await asyncio.wait_for(entered.wait(), 3)
                    busy = await client.post(url, content=forbidden_body(), headers=headers)
                    assert busy.status_code == 503 and busy.json()["error"] == "broker_busy"
                    cancelled = await client.post("/v1/admin/revoke", json={"grant_id": grant.jti}, headers=admin)
                    assert cancelled.status_code == 200
                finally:
                    release.set()
                result = await asyncio.wait_for(pending, 10)
                assert result.status_code == 409
                assert app.state.lifecycle.registry.find_operation(attempt_id, "held") is None
    asyncio.run(scenario())
    registry = Registry(config.registry_path)
    assert DockerDriver(registry.broker_id, IMAGE).owned_inventory() == []


def test_node_pi_tools_through_real_broker(environment):
    config, grant, token, archive = environment
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(create_app(config), log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
        with httpx.Client(base_url=origin, timeout=30, trust_env=False) as client:
            attempt_id = initialize(client, config, token, archive)
        lease = {"runId": grant.run, "workspaceId": grant.project, "attemptId": attempt_id, "grant": token, "deadline": grant.exp}
        result = subprocess.run(["node", "--import", "tsx", "--test", "src/broker-integration.test.ts"],
            cwd=Path(__file__).resolve().parents[3] / "runtime", capture_output=True, text=True, encoding="utf-8", timeout=90,
            env={**os.environ, "ATOM_TEST_BROKER_ORIGIN": origin, "ATOM_TEST_BROKER_LEASE": json.dumps(lease)})
        assert result.returncode == 0, result.stdout + result.stderr
        registry = Registry(config.registry_path)
        assert registry.find(attempt_id).state == "terminated"
        assert DockerDriver(registry.broker_id, IMAGE).owned_inventory() == []
    finally:
        server.should_exit = True
        thread.join(timeout=20)
        listener.close()
    assert not thread.is_alive()


def test_scoped_release_cannot_target_successor_and_is_idempotent(environment):
    config, grant, token, archive = environment
    with TestClient(create_app(config)) as client:
        old_id = initialize(client, config, token, archive)
        headers = {"authorization": "Bearer " + token}
        assert client.get(f"/v1/attempts/{old_id}", headers=headers).json()["state"] == "ready"
        assert client.post(f"/v1/attempts/{old_id}/release", headers=headers).json()["state"] == "terminated"
        next_grant = replace(grant, jti="next", attempt="next", fence=2)
        next_token = GrantCodec(config.grant_key.encode()).issue(next_grant)
        next_id = initialize(client, config, next_token, archive)
        assert client.post(f"/v1/attempts/{next_id}/release", headers=headers).status_code == 409
        assert client.post(f"/v1/attempts/{old_id}/release", headers=headers).json()["state"] == "terminated"
        assert client.get(f"/v1/attempts/{next_id}", headers={"authorization": "Bearer " + next_token}).json()["state"] == "ready"
        assert client.get(f"/v1/attempts/{old_id}", headers=headers).status_code == 409
