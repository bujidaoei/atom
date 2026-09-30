import json
import pytest
from app.db import session_scope
from app.models import Requirement
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
