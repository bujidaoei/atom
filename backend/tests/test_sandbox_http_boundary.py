from dataclasses import replace
import asyncio
import secrets
import time

import pytest
from fastapi.testclient import TestClient

from app.sandbox.config import BrokerConfig, ConfigError
from app.sandbox.grants import Grant, GrantCodec
from app.sandbox.service import create_app, _body, ServiceError
from starlette.requests import Request


@pytest.fixture
def config(tmp_path):
    return BrokerConfig(tmp_path / "broker.db", "sha256:" + "a" * 64,
                        secrets.token_urlsafe(32), secrets.token_urlsafe(32))


@pytest.mark.parametrize("field,value", [
    ("admin_token", "short"), ("grant_key", "dev-secret" * 5),
    ("grant_key", "x" * 129), ("grant_key", "é" * 32),
    ("image", "python:latest"), ("sweep_seconds", 0), ("sweep_seconds", True),
    ("batch_size", 1001), ("port", 80),
])
def test_config_rejects_unsafe_values(config, field, value):
    with pytest.raises(ConfigError):
        replace(config, **{field: value})


def test_explicit_config_has_no_secret_repr_or_fallback(config):
    assert config.admin_token not in repr(config) and config.grant_key not in repr(config)
    with pytest.raises(ConfigError):
        replace(config, grant_key=config.admin_token)
    with pytest.raises(ConfigError, match="^invalid_broker_configuration$"):
        BrokerConfig.from_env({})
    assert not config.registry_path.exists()
    env = {"ATOM_BROKER_REGISTRY_PATH": str(config.registry_path), "ATOM_BROKER_IMAGE": config.image,
           "ATOM_BROKER_ADMIN_TOKEN": config.admin_token, "ATOM_BROKER_GRANT_KEY": config.grant_key}
    assert BrokerConfig.from_env(env) == config
    with pytest.raises(ConfigError):
        BrokerConfig.from_env({**env, "ATOM_RUNTIME_TOKEN": config.admin_token})


@pytest.mark.parametrize("payload,status", [
    ('{"grant":"x","grant":"y"}', 400), ('{"grant":true}', 400),
    ('{"grant":"x","command":"shell"}', 400), ('{"grant":NaN}', 400),
    ('[]', 400), ('{"grant":"x"}', 403), ('x' * 12289, 413),
])
def test_denied_bodies_have_no_registry_effects_without_lifespan(config, payload, status):
    client = TestClient(create_app(config))
    response = client.post("/v1/admin/provision", content=payload,
        headers={"authorization": "Bearer " + config.admin_token, "content-type": "application/json"})
    assert response.status_code == status
    assert config.admin_token not in response.text and config.grant_key not in response.text
    assert not config.registry_path.exists()


def test_runtime_grant_and_duplicate_authorization_cannot_administer(config):
    client = TestClient(create_app(config))
    now = int(time.time())
    token = GrantCodec(config.grant_key.encode()).issue(
        Grant("g", "o", "p", "r", "a", 1, "a" * 64, now, now + 30))
    for headers in ({}, {"authorization": "Bearer " + token},
                    [("authorization", "Bearer " + config.admin_token), ("authorization", "Bearer " + config.admin_token)]):
        response = client.post("/v1/admin/provision", content=b"x" * 20000, headers=headers)
        assert response.status_code == 401
    assert not config.registry_path.exists()


def test_content_encoding_and_media_type_rejected(config):
    client = TestClient(create_app(config))
    base = {"authorization": "Bearer " + config.admin_token}
    for headers in ({**base, "content-type": "text/plain"},
                    {**base, "content-type": "application/json", "content-encoding": "gzip"}):
        assert client.post("/v1/admin/provision", content='{"grant":"x"}', headers=headers).status_code == 415


def test_stalled_stream_has_a_real_read_deadline():
    async def receive():
        await asyncio.sleep(60)
        raise AssertionError("read should have timed out")
    request = Request({"type": "http", "headers": [(b"content-type", b"application/json")]}, receive)
    started = time.monotonic()
    with pytest.raises(ServiceError) as error:
        asyncio.run(_body(request, "grant"))
    assert error.value.status == 408
    assert 4 <= time.monotonic() - started < 8
