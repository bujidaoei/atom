import json

from app.services import pipeline


PLAN = {
    "name": "今日烘焙",
    "lead": "第一版只做售罄看板，不做收银。",
    "research": "店员在柜台边用，最大的风险是刷新后把状态弄丢。",
    "architecture": "单页。数据存在 localStorage 键 bake-board。",
    "requirements": [
        {
            "key": "R1",
            "title": "记下售罄",
            "detail": "输入名称后点记下，列表出现该名称",
            "priority": "must",
            "checks": [
                {"op": "exists", "selector": "#item-title"},
                {
                    "op": "flow",
                    "steps": [
                        {"do": "fill", "selector": "#item-title", "value": "可颂"},
                        {"do": "click", "selector": "#add-item"},
                        {"do": "see", "contains": "可颂"},
                    ],
                },
            ],
        },
        {
            "key": "R2",
            "title": "看到店名",
            "detail": "页头写着今日烘焙",
            "priority": "must",
            "checks": [{"op": "text", "contains": "今日烘焙"}, {"op": "exists", "selector": "#page-title"}],
        },
        {
            "key": "R3",
            "title": "可以记下",
            "detail": "有一个记下按钮",
            "priority": "must",
            "checks": [{"op": "exists", "selector": "#add-item"}],
        },
    ],
}

PAGE = """<!DOCTYPE html>
<html><head><title>今日烘焙</title></head>
<body>
  <h1 id="page-title">今日烘焙</h1>
  <input id="item-title" />
  <button id="add-item">记下</button>
  <ul id="item-list"></ul>
</body></html>
"""

BUILD = f"""NOTES
按契约做了售罄看板。

TRACE
R1 | #item-title 写入列表
R2 | #page-title
R3 | #add-item

HTML
{PAGE}
"""


async def _fake_complete(**kwargs):
    system = kwargs["messages"][0]["content"]
    if system.startswith("你是 Mike"):
        return "第一版只做售罄看板，不做收银。\n@Iris 先看风险。\n@Bob 定键。\n@Emma 写契约。", {
            "prompt_tokens": 4,
            "completion_tokens": 8,
            "model": "test",
        }
    if system.startswith("你是 Iris"):
        return "店员在柜台边用。最大的风险是刷新后把状态弄丢。\n@Bob 按这个定结构。", {
            "prompt_tokens": 4,
            "completion_tokens": 8,
            "model": "test",
        }
    if system.startswith("你是 Bob"):
        return "单页。数据存在 localStorage 键 bake-board。\n@Emma 按这个写契约。", {
            "prompt_tokens": 4,
            "completion_tokens": 8,
            "model": "test",
        }
    if "requirements" in system and "localStorage" in system and "NOTES" not in system:
        return json.dumps(PLAN, ensure_ascii=False), {"prompt_tokens": 10, "completion_tokens": 20, "model": "test"}
    if "compatible" in system or "amend" in system:
        return json.dumps({"kind": "compatible", "reason": "只是措辞，契约还在。"}), {
            "prompt_tokens": 3,
            "completion_tokens": 4,
            "model": "test",
        }
    return BUILD, {"prompt_tokens": 30, "completion_tokens": 40, "model": "test"}


def _register(client):
    response = client.post(
        "/api/auth/register",
        json={"name": "林深", "email": "lin@example.com", "password": "correct-horse"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_register_login_and_settings_mask(client, monkeypatch):
    monkeypatch.setattr(pipeline, "complete", _fake_complete)
    user = _register(client)
    assert user["email"] == "lin@example.com"
    me = client.get("/api/auth/me")
    assert me.status_code == 200

    settings = client.get("/api/settings")
    body = settings.json()
    assert body["api_key_source"] == "server"
    assert body["api_key_masked"].startswith("sk")
    assert body["api_key_masked"].endswith("AB")
    assert "sk-testkeyAB" not in settings.text

    updated = client.put("/api/settings", json={"api_key": "sk-personalKEY"})
    assert updated.json()["api_key_source"] == "user"
    assert "sk-personalKEY" not in updated.text
    cleared = client.delete("/api/settings/api-key")
    assert cleared.json()["api_key_source"] == "server"

    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401
    login = client.post("/api/auth/login", json={"email": "lin@example.com", "password": "wrong-password"})
    assert login.status_code == 401
    login = client.post("/api/auth/login", json={"email": "lin@example.com", "password": "correct-horse"})
    assert login.status_code == 200


def test_plan_build_and_acceptance(client, monkeypatch):
    monkeypatch.setattr(pipeline, "complete", _fake_complete)
    _register(client)
    created = client.post("/api/projects", json={"prompt": "给咖啡馆做一个今日烘焙售罄看板"})
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]

    planned = client.post(f"/api/projects/{project_id}/plan")
    assert planned.status_code == 200, planned.text
    body = planned.json()
    assert body["status"] == "awaiting_approval"
    assert body["name"] == "今日烘焙"
    assert len(body["requirements"]) == 3
    roles = [message["role"] for message in body["messages"]]
    assert roles[:5] == ["system", "mike", "iris", "bob", "emma"]
    assert body["messages"][1]["activity"][0]["title"] == "读取这条需求"
    assert any(message["role"] == "emma" for message in body["messages"])

    built = client.post(f"/api/projects/{project_id}/build")
    assert built.status_code == 200, built.text
    built_body = built.json()
    assert built_body["status"] == "ready"
    assert built_body["contract_locked"] is True
    assert "今日烘焙" in built_body["html"]

    accepted = client.post(
        f"/api/projects/{project_id}/acceptance",
        json={"runtime": [{"key": "R1", "index": 1, "ok": True, "detail": "看到了可颂"}]},
    )
    report = accepted.json()["latest_acceptance"]
    assert report["passed"] == 3
    assert report["total"] == 3

    state = client.put(
        f"/api/projects/{project_id}/preview-state",
        json={"snapshot": {"bake-board": "[\"可颂\"]"}},
    )
    assert state.status_code == 200
    again = client.get(f"/api/projects/{project_id}")
    assert again.json()["preview_state"]["bake-board"] == '["可颂"]'

    usage = client.get("/api/usage")
    assert usage.json()["calls"] >= 2

    listed = client.get("/api/projects")
    assert len(listed.json()) == 1
    assert client.delete(f"/api/projects/{project_id}").status_code == 200
    assert client.get("/api/projects").json() == []
