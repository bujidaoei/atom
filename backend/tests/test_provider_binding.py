from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope
from app.errors import AtomError
from app.models import User, UserSettings
from app.services.orchestrator import _gateway_for


@pytest.fixture
def provider(monkeypatch):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            key = self.headers.get("Authorization")
            requests.append((self.path, key))
            if self.path.startswith("/broken"):
                self.send_response(503)
                self.end_headers()
                return
            if self.path.startswith("/redirect"):
                self.send_response(302)
                self.send_header("Location", "/unexpected/models")
                self.end_headers()
                return
            payload = {"data": [{"id": "catalog-b" if key == "Bearer user-b-same99" else "catalog-a"}]}
            if self.path.startswith("/malformed"):
                payload = {"data": {"id": "not-a-list"}}
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    root = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setenv("no_proxy", "*")
    monkeypatch.setattr(get_settings(), "llm_base_url", root + "/managed")
    monkeypatch.setattr(get_settings(), "llm_api_key", "synthetic-managed-key")
    try:
        yield root, requests
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def user_id():
    with session_scope() as db:
        return db.scalar(select(User.id))


def test_endpoint_only_update_does_not_send_managed_key(signed_in, provider):
    root, requests = provider
    response = signed_in.put("/api/settings", json={"baseUrl": root + "/custom"})
    assert response.status_code == 400
    assert requests == []
    body = signed_in.get("/api/settings").json()
    assert body["baseUrl"] == root + "/managed"
    assert requests == [("/managed/models", "Bearer synthetic-managed-key")]


def test_complete_custom_connection_and_reset_bind_both_fields(signed_in, provider):
    root, requests = provider
    response = signed_in.put("/api/settings", json={"baseUrl": root + "/custom", "apiKey": "user-key"})
    assert response.status_code == 200
    for planning in (True, False):
        connection = _gateway_for(user_id(), planning=planning)
        assert (connection.base_url, connection.api_key) == (root + "/custom", "user-key")
    body = signed_in.delete("/api/settings/api-key").json()
    assert body["baseUrl"] == root + "/managed"
    assert body["source"] == "server"
    assert ("/custom/models", "Bearer synthetic-managed-key") not in requests


def test_rebinding_existing_key_requires_explicit_credential(signed_in, provider):
    root, requests = provider
    body = signed_in.put("/api/settings", json={"baseUrl": root + "/first", "apiKey": "user-key"}).json()
    count = len(requests)
    for patch in ({"baseUrl": root + "/second"}, {"baseUrl": root + "/second", "apiKey": body["apiKeyMasked"]}):
        assert signed_in.put("/api/settings", json=patch).status_code == 400
    assert len(requests) == count
    assert _gateway_for(user_id()).base_url == root + "/first"
    assert signed_in.put("/api/settings", json={"baseUrl": root + "/second", "apiKey": "replacement-key"}).status_code == 200
    assert requests[-1] == ("/second/models", "Bearer replacement-key")


def test_legacy_unsafe_settings_are_readable_but_cannot_execute(signed_in, provider):
    root, requests = provider
    uid = user_id()
    with session_scope() as db:
        settings = db.get(UserSettings, uid)
        settings.base_url = root + "/legacy"
        settings.api_key = None
    response = signed_in.get("/api/settings")
    assert response.status_code == 200
    assert response.json()["configurationError"]
    assert response.json()["modelsStatus"] == "unconfigured"
    assert response.json()["apiKeyMasked"] == ""
    assert requests == []
    with pytest.raises(AtomError):
        _gateway_for(uid)
    assert signed_in.put("/api/settings", json={"apiKey": "repaired-key"}).status_code == 200


@pytest.mark.parametrize("endpoint", [
    "ftp://provider.invalid/v1", "https://user:pass@provider.invalid/v1",
    "https://provider.invalid/v1?key=x", "https://provider.invalid/v1#fragment",
    "https://provider.invalid:bad/v1", "https://provider.invalid/a/../v1",
    "https://provider.invalid\\@other.invalid/v1", "https://provider.invalid/%2e%2e/v1",
    "https://provider.invalid/\nv1", "https:///v1",
    "\nhttps://provider.invalid/v1", "https://provider.invalid:/v1",
])
def test_ambiguous_endpoint_rejected_without_request(signed_in, provider, endpoint):
    _, requests = provider
    assert signed_in.put("/api/settings", json={"baseUrl": endpoint, "apiKey": "user-key"}).status_code == 400
    assert requests == []


def test_distinct_credentials_with_same_suffix_do_not_share_catalog(signed_in, provider):
    root, _ = provider
    first = signed_in.put("/api/settings", json={"baseUrl": root + "/custom", "apiKey": "user-a-same99"}).json()
    second = signed_in.put("/api/settings", json={"apiKey": "user-b-same99"}).json()
    assert first["models"] == [{"id": "catalog-a"}]
    assert second["models"] == [{"id": "catalog-b"}]


@pytest.mark.parametrize("path", ["broken", "malformed", "redirect"])
def test_failed_discovery_never_fabricates_models(signed_in, provider, path):
    root, requests = provider
    body = signed_in.put("/api/settings", json={"baseUrl": root + "/" + path, "apiKey": "user-key"}).json()
    assert body["models"] == []
    assert body["modelsStatus"] == "unavailable"
    assert len(requests) == 1


def test_personal_key_stays_at_pinned_endpoint_if_server_config_changes(signed_in, provider, monkeypatch):
    root, _ = provider
    assert signed_in.put("/api/settings", json={"apiKey": "personal-key"}).status_code == 200
    monkeypatch.setattr(get_settings(), "llm_base_url", root + "/other-server")
    assert _gateway_for(user_id()).base_url == root + "/managed"


@pytest.mark.parametrize("key", ["abc\r\n", "has space", "密钥"])
def test_bad_credentials_rejected_without_transport(signed_in, provider, key):
    _, requests = provider
    assert signed_in.put("/api/settings", json={"apiKey": key}).status_code == 400
    assert requests == []


def test_equivalent_default_endpoint_and_masked_key_preserve_binding(signed_in, provider):
    root, _ = provider
    assert signed_in.put("/api/settings", json={"baseUrl": root + "/managed/"}).status_code == 200
    body = signed_in.put("/api/settings", json={"apiKey": "personal-key"}).json()
    assert signed_in.put("/api/settings", json={"apiKey": body["apiKeyMasked"]}).status_code == 200
    assert _gateway_for(user_id()).api_key == "personal-key"


def test_missing_managed_key_is_repairable_without_network(signed_in, provider, monkeypatch):
    _, requests = provider
    monkeypatch.setattr(get_settings(), "llm_api_key", "")
    body = signed_in.get("/api/settings").json()
    assert body["source"] == "unconfigured"
    assert body["configurationError"]
    assert requests == []
