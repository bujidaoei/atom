from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_reports_runtime_state(client: TestClient) -> None:
    response = client.get("/api/health")
    body = response.json()
    assert response.status_code == 503
    assert body["ok"] is False
    # Unreachable runtime must fail readiness instead of a healthy HTTP result.
    assert body["runtime"] is False


def test_lookup_distinguishes_known_and_unknown_emails(client: TestClient) -> None:
    assert client.post("/api/auth/lookup", json={"email": "nobody@example.com"}).json() == {
        "email": "nobody@example.com",
        "exists": False,
    }
    client.post(
        "/api/auth/register", json={"email": "Someone@Example.com", "password": "s3cretpass"}
    )
    assert client.post("/api/auth/lookup", json={"email": "someone@example.com"}).json()[
        "exists"
    ] is True


def test_register_rejects_weak_and_duplicate_credentials(client: TestClient) -> None:
    assert (
        client.post(
            "/api/auth/register", json={"email": "a@b.com", "password": "12345678"}
        ).status_code
        == 400
    )
    assert (
        client.post("/api/auth/register", json={"email": "a@b.com", "password": "short"}).status_code
        == 422
    )
    client.post("/api/auth/register", json={"email": "a@b.com", "password": "s3cretpass"})
    assert (
        client.post(
            "/api/auth/register", json={"email": "A@B.com", "password": "s3cretpass"}
        ).status_code
        == 409
    )


def test_login_round_trip(client: TestClient) -> None:
    client.post("/api/auth/register", json={"email": "a@b.com", "password": "s3cretpass"})
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401
    assert (
        client.post("/api/auth/login", json={"email": "a@b.com", "password": "wrongpass1"}).status_code
        == 401
    )
    assert client.post("/api/auth/login", json={"email": "a@b.com", "password": "s3cretpass"}).status_code == 200
    assert client.get("/api/auth/me").json()["email"] == "a@b.com"


def test_settings_mask_and_preserve_stored_key(signed_in: TestClient) -> None:
    body = signed_in.get("/api/settings").json()
    # "sk-testtesttesttest12" is 21 characters: two shown, 17 hidden, two shown.
    assert body["apiKeyMasked"] == "sk" + "*" * 17 + "12"
    assert body["source"] == "server"

    signed_in.put("/api/settings", json={"apiKey": "sk-userkey-abcdef99"})
    body = signed_in.get("/api/settings").json()
    assert body["source"] == "user"
    assert body["apiKeyMasked"] == "sk" + "*" * 15 + "99"

    # Echoing the masked value back must not clobber the real key.
    signed_in.put("/api/settings", json={"apiKey": body["apiKeyMasked"]})
    assert signed_in.get("/api/settings").json()["apiKeyMasked"] == body["apiKeyMasked"]

    signed_in.delete("/api/settings/api-key")
    assert signed_in.get("/api/settings").json()["source"] == "server"


def test_settings_reject_bad_base_url(signed_in: TestClient) -> None:
    assert signed_in.put("/api/settings", json={"baseUrl": "ftp://nope"}).status_code == 400


def test_project_lifecycle(signed_in: TestClient) -> None:
    created = signed_in.post("/api/projects", json={"prompt": "做一个极简待办清单"})
    assert created.status_code == 201, created.text
    project = created.json()["project"]
    assert project["status"] == "draft"
    assert project["title"] == "做一个极简待办清单"
    assert [m["role"] for m in project["messages"]] == ["user"]

    listed = signed_in.get("/api/projects").json()["projects"]
    assert [p["id"] for p in listed] == [project["id"]]

    assert signed_in.get(f"/api/projects/{project['id']}").status_code == 200
    assert signed_in.delete(f"/api/projects/{project['id']}").json() == {"ok": True}
    assert signed_in.get(f"/api/projects/{project['id']}").status_code == 404


def test_projects_are_scoped_to_their_owner(client: TestClient) -> None:
    client.post("/api/auth/register", json={"email": "one@b.com", "password": "s3cretpass"})
    project_id = client.post("/api/projects", json={"prompt": "第一个人的项目"}).json()["project"]["id"]
    client.post("/api/auth/logout")

    client.post("/api/auth/register", json={"email": "two@b.com", "password": "s3cretpass"})
    assert client.get(f"/api/projects/{project_id}").status_code == 404
    assert client.get("/api/projects").json()["projects"] == []


def test_actions_rejected_in_the_wrong_state(signed_in: TestClient) -> None:
    project_id = signed_in.post("/api/projects", json={"prompt": "记账工具"}).json()["project"]["id"]
    # A draft has no contract to approve and nothing built to revise.
    assert signed_in.post(f"/api/projects/{project_id}/approve", json={}).status_code == 409
    assert (
        signed_in.post(f"/api/projects/{project_id}/revise", json={"message": "改改"}).status_code
        == 409
    )


def test_publish_requires_a_built_page(signed_in: TestClient) -> None:
    project_id = signed_in.post("/api/projects", json={"prompt": "作品集"}).json()["project"]["id"]
    assert signed_in.post(f"/api/projects/{project_id}/publish").status_code == 409


def test_broker_publish_rejects_stale_legacy_workspace(signed_in: TestClient, monkeypatch) -> None:
    from app import storage
    from app.config import get_settings
    from app.db import session_scope
    from app.models import Project, Publication

    project_id = signed_in.post("/api/projects", json={"prompt": "作品集"}).json()["project"]["id"]
    with session_scope() as session:
        session.get(Project, project_id).status = "ready"
    (storage.workspace_dir(project_id) / "index.html").write_text(
        "stale mutable bytes", encoding="utf-8"
    )
    monkeypatch.setattr(get_settings(), "sandbox_mode", "broker")

    response = signed_in.post(f"/api/projects/{project_id}/publish")
    assert response.status_code == 409
    assert "旧发布入口" in response.json()["detail"]
    with session_scope() as session:
        assert session.get(Project, project_id).slug is None
        assert session.query(Publication).count() == 0


def test_broker_adoption_does_not_copy_stale_legacy_heat(signed_in: TestClient, monkeypatch) -> None:
    from app import storage
    from app.config import get_settings
    from app.db import session_scope
    from app.models import Project, Race, RaceHeat

    project_id = signed_in.post("/api/projects", json={"prompt": "赛道测试"}).json()["project"]["id"]
    with session_scope() as session:
        session.get(Project, project_id).status = "ready"
        session.add(Race(id="race", project_id=project_id, status="done"))
        session.add(RaceHeat(id="heat", race_id="race", model="fixture", status="done"))
    main = storage.workspace_dir(project_id) / "index.html"
    main.write_text("current main", encoding="utf-8")
    branch = storage.workspace_dir(project_id, "heat")
    branch.mkdir(parents=True)
    (branch / "index.html").write_text("stale heat", encoding="utf-8")
    monkeypatch.setattr(get_settings(), "sandbox_mode", "broker")

    response = signed_in.post(f"/api/projects/{project_id}/race/heat/adopt")
    assert response.status_code in (403, 404)
    assert main.read_text(encoding="utf-8") == "current main"
    with session_scope() as session:
        assert session.get(Race, "race").winner_heat_id is None
        assert session.get(Project, project_id).status == "ready"


def test_local_adoption_does_not_copy_unregistered_heat(signed_in: TestClient) -> None:
    from app import storage
    from app.db import session_scope
    from app.models import Project, Race, RaceHeat

    project_id = signed_in.post("/api/projects", json={"prompt": "本地赛道"}).json()["project"]["id"]
    with session_scope() as session:
        session.add(Race(id="local-race", project_id=project_id, status="done"))
        session.add(RaceHeat(id="local-heat", race_id="local-race", model="fixture", status="done"))
    branch = storage.workspace_dir(project_id, "local-heat")
    branch.mkdir(parents=True)
    (branch / "index.html").write_text("completed local heat", encoding="utf-8")

    response = signed_in.post(f"/api/projects/{project_id}/race/local-heat/adopt")
    assert response.status_code in (403, 404)
    assert not (storage.workspace_dir(project_id) / "index.html").exists()
    with session_scope() as session:
        assert session.get(Race, "local-race").winner_heat_id is None


def test_race_validates_model_selection(signed_in: TestClient) -> None:
    project_id = signed_in.post("/api/projects", json={"prompt": "落地页"}).json()["project"]["id"]
    # Fewer than two models never reaches the handler.
    assert (
        signed_in.post(f"/api/projects/{project_id}/race", json={"models": ["a"]}).status_code
        == 422
    )
    # A race needs a contract to build against, so a draft is refused.
    assert (
        signed_in.post(f"/api/projects/{project_id}/race", json={"models": ["a", "b"]}).status_code
        == 409
    )


def test_usage_starts_empty(signed_in: TestClient) -> None:
    body = signed_in.get("/api/usage").json()
    assert body == {
        "credits": 10,
        "spent": 0,
        "runs": 0,
        "inputTokens": 0,
        "outputTokens": 0,
        "ledger": [],
    }


def test_unknown_api_path_returns_json_404(client: TestClient) -> None:
    response = client.get("/api/definitely-not-a-route")
    assert response.status_code == 404
    assert "未知接口" in response.json()["detail"]


def test_legacy_user_does_not_offer_account_revocation(signed_in):
    assert signed_in.get('/api/auth/me').json()['canRevokeSessions'] is False
    assert signed_in.post('/api/auth/logout-all').status_code == 404
