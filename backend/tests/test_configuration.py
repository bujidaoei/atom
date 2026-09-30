from __future__ import annotations

import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import subprocess
import sys
from threading import Thread

import pytest
from pydantic import ValidationError

from app.config import Settings

BASE = dict(secret="synthetic-session-signing-key-32-characters",
            runtime_token="synthetic-runtime-service-key-32-characters",
            runtime_url="http://127.0.0.1:8721", cookie_secure=True)

BROKER = dict(broker_origin='http://127.0.0.1:8766', artifact_dir=os.path.abspath('private-artifacts'),
              broker_admin_token='synthetic-broker-admin-key-32-characters',
              broker_grant_key='synthetic-broker-grant-key-32-characters',
              completion_grant_key='synthetic-completion-key-32-characters')


@pytest.mark.parametrize("patch", [
    {"secret": ""}, {"secret": "dev-secret-change-me"},
    {"secret": "sensitive-short-value"}, {"runtime_token": ""},
    {"runtime_token": "change-me-to-a-real-random-service-token"},
    {"runtime_token": "synthetic-value-with-newline-123456\n"},
    {"runtime_token": BASE["secret"]}, {"environment": "prodution"},
    {"environment": "production", "cookie_secure": False},
    {"environment": "production", "runtime_url": "http://worker.invalid:8721"},
    {"runtime_url": "http://user:secret@127.0.0.1:8721"},
    {"runtime_url": "http://127.0.0.1:8721?key=x"},
    {"runtime_url": "http://127.0.0.1:8721#fragment"},
    {"session_days": 0}, {"run_timeout_seconds": -1}, {"cookie_path": "relative"},
])
def test_configuration_rejects_invalid_or_unsafe_values(patch):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **(BASE | patch))


def test_valid_production_transport_and_redacted_representation():
    settings = Settings(_env_file=None, **(BASE | BROKER | {"environment": "production"}))
    assert settings.cookie_secure
    assert BASE["secret"] not in repr(settings)
    assert BASE["runtime_token"] not in repr(settings)
    assert settings.sandbox_mode == 'broker'
    assert all(value not in repr(settings) for key,value in BROKER.items() if key.endswith(('token','key')))
    assert Settings(_env_file=None, **(BASE | BROKER | {"environment": "production", "runtime_url": "https://runtime.invalid"}))


@pytest.mark.parametrize('patch', [
    {'sandbox_mode':'local'}, {'broker_origin':None}, {'broker_origin':'http://broker.invalid'},
    {'broker_origin':'http://127.0.0.1:8766/path'}, {'artifact_dir':'relative'},
    {'broker_admin_token':None}, {'broker_grant_key':'short'},
    {'completion_grant_key':BROKER['broker_grant_key']}, {'broker_admin_token':BASE['runtime_token']},
    {'run_timeout_seconds':7200},
])
def test_production_requires_distinct_complete_broker_configuration(patch):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **(BASE | BROKER | {'environment':'production'} | patch))


def test_local_execution_routes_are_unavailable(client):
    for action in ('complete','cancel'):
        response=client.post('/v1/executions/'+action)
        assert response.status_code==503 and response.json()=={'error':'execution_unavailable'}


def test_invalid_startup_does_not_log_configuration_secrets(tmp_path):
    value = "do-not-echo-this-secret\ninvalid-input"
    result = subprocess.run([sys.executable, "-c", "from app.config import get_settings; get_settings()"],
                            env=os.environ | {"ATOM_SECRET": value, "ATOM_DATA_DIR": str(tmp_path / "data")},
                            text=True, capture_output=True, timeout=10)
    assert result.returncode != 0
    assert "do-not-echo-this-secret" not in result.stdout + result.stderr
    assert not (tmp_path / "data").exists()


def test_runtime_health_uses_authentication_and_detects_rejection(monkeypatch, client):
    from app import main
    from app.config import get_settings
    from app.services.runtime_client import RuntimeClient
    expected = get_settings().runtime_token
    observed = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            authorized = self.headers.get("Authorization") == f"Bearer {expected}"
            observed.append(authorized)
            self.send_response(200 if authorized else 401)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        monkeypatch.setenv("NO_PROXY", "*")
        monkeypatch.setattr(get_settings(), "runtime_url", f"http://127.0.0.1:{server.server_port}")
        monkeypatch.setattr(main, "runtime_client", RuntimeClient())
        healthy = client.get("/api/health")
        assert healthy.status_code == 200
        assert healthy.json() == {"ok": True, "runtime": True}
        monkeypatch.setattr(get_settings(), 'sandbox_mode', 'broker')
        unavailable=client.get('/api/health')
        assert unavailable.status_code==503
        assert unavailable.json()=={'ok':False,'runtime':True,'broker':False}
        monkeypatch.setattr(get_settings(), 'sandbox_mode', 'local')
        monkeypatch.setattr(get_settings(), "runtime_token", "different-synthetic-runtime-token-12345")
        monkeypatch.setattr(main, "runtime_client", RuntimeClient())
        rejected = client.get("/api/health")
        assert rejected.status_code == 503
        assert rejected.json() == {"ok": False, "runtime": False}
        assert observed == [True, True, False]
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
