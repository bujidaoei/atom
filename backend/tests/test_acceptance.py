import json
from datetime import datetime, timedelta, timezone
import pytest
from app.db import session_scope
from app.models import AcceptanceRun, Requirement, Run
from app.serialize import acceptance_json
from app.services.parsing import _normalize_check


def test_setup_preserved_and_invalid_setup_rejected():
    check = {
        "type": "flow",
        "selector": "#add",
        "expect": "#item",
        "setup": [
            {"action": "fill", "selector": "#name", "value": "Alice"},
            {"action": "press", "selector": "#name", "key": "Enter"},
        ],
    }
    assert _normalize_check(check) == check
    for setup in [
        [{"action": "execute", "selector": "#name"}],
        "bad",
        [{"action": "fill", "selector": "#name"}],
    ]:
        with pytest.raises(ValueError):
            _normalize_check({**check, "setup": setup})


def test_reports_require_exact_unique_contract_coverage(signed_in):
    pid = signed_in.post("/api/projects", json={"prompt": "test acceptance"}).json()[
        "project"
    ]["id"]
    with session_scope() as session:
        session.add(
            Requirement(
                project_id=pid,
                key="name",
                title="name",
                checks_json=json.dumps(
                    [
                        {"type": "exists", "selector": "#name"},
                        {"type": "exists", "selector": "#add"},
                    ]
                ),
            )
        )
    endpoint = f"/api/projects/{pid}/acceptance"
    one = {"key": "name", "checkIndex": 0, "passed": True}
    two = {**one, "checkIndex": 1}
    for results in [[one], [one, one], [one, two, two], [one, {**two, "key": "fake"}]]:
        assert signed_in.post(endpoint, json={"results": results}).status_code == 422
    response = signed_in.post(endpoint, json={"results": [one, two]})
    assert response.status_code == 200
    assert response.json()["acceptance"]["passed"] == 2


@pytest.mark.parametrize("phase", ["build", "revise", "race"])
def test_checks_save_and_reload_after_generation(signed_in, phase):
    pid = signed_in.post("/api/projects", json={"prompt": "check generated page"}).json()["project"]["id"]
    with session_scope() as session:
        session.add(Requirement(project_id=pid, key="button", title="Button",
            checks_json=json.dumps([{"type": "exists", "selector": "button"}])))
        session.add(Run(project_id=pid, role="engineer", model="test-model",
            phase=phase, status="succeeded", started_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
    response = signed_in.post(f"/api/projects/{pid}/acceptance", json={"results": [
        {"key": "button", "checkIndex": 0, "passed": False, "note": "button missing"}]})
    assert response.status_code == 200
    result = response.json()["acceptance"]
    assert (result["passed"], result["total"]) == (0, 1)
    assert datetime.fromisoformat(result["createdAt"]).utcoffset() == timedelta(0)
    reloaded = signed_in.get(f"/api/projects/{pid}").json()["project"]["acceptance"]
    assert reloaded == result


def test_stale_checks_hidden_with_retained_and_reloaded_timestamps(signed_in):
    pid = signed_in.post("/api/projects", json={"prompt": "stale checks"}).json()["project"]["id"]
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        # Retain the inserted object to reproduce expire_on_commit=False.
        check = AcceptanceRun(project_id=pid, passed=1, total=1,
            results_json="[]", created_at=now - timedelta(minutes=2))
        session.add(check)
        session.add(Run(project_id=pid, role="engineer", model="test-model",
            phase="revise", status="succeeded", started_at=now))
        session.commit()
        assert acceptance_json(session, pid) is None
        session.expire_all()
        assert acceptance_json(session, pid) is None
