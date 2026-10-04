import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select

from app import storage
from app.db import session_scope
from app.models import CommandReceipt, Project, Race, RaceHeat, Run, User
from app.services.orchestrator import Orchestrator, orchestrator
from app.services.runtime_client import RuntimeLine


async def waiting(*args, **kwargs):
    await asyncio.sleep(60)


@pytest.mark.parametrize(
    "action,initial,body",
    [
        ("plan", "draft", None),
        ("approve", "awaiting_approval", {}),
        ("revise", "ready", {"message": "change color"}),
    ],
)
def test_command_replay_survives_terminal_state_and_rejects_changed_payload(
    signed_in, monkeypatch, action, initial, body
):
    monkeypatch.setattr(orchestrator, "_plan", waiting)
    monkeypatch.setattr(orchestrator, "_build", waiting)
    pid = signed_in.post("/api/projects", json={"prompt": "test app"}).json()[
        "project"
    ]["id"]
    with session_scope() as s:
        s.get(Project, pid).status = initial
        if action == 'approve':
            from app.contract_history import commit_snapshot
            snapshot = commit_snapshot(s, pid, {
                'requirements': [{'key': 'app', 'title': 'App', 'detail': '',
                                  'checks': [{'type': 'exists', 'selector': 'main'}]}],
                'scope': ['App'], 'outOfScope': [], 'architecture': '', 'notes': [],
            }, expected=None, note='Initial contract')
            body = {'expectedVersion': snapshot['id']}
    headers = {"Idempotency-Key": "same-command"}

    def send():
        return signed_in.post(
            f"/api/projects/{pid}/{action}", json=body, headers=headers
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: send(), range(2)))
    assert [r.status_code for r in responses] == [200, 200]
    assert responses[0].json() == responses[1].json()
    assert signed_in.get(f"/api/projects/{pid}").json()["project"]["status"] in {
        "planning",
        "building",
    }
    assert signed_in.post(f"/api/projects/{pid}/cancel").status_code == 200
    assert send().json() == responses[0].json()
    assert (
        signed_in.get(f"/api/projects/{pid}").json()["project"]["status"] == "cancelled"
    )
    other = "revise" if action != "revise" else "approve"
    assert (
        signed_in.post(
            f"/api/projects/{pid}/{other}",
            json={"message": "different"},
            headers=headers,
        ).status_code
        == 409
    )
    with session_scope() as s:
        assert (
            len(
                list(
                    s.scalars(
                        select(CommandReceipt).where(CommandReceipt.project_id == pid)
                    )
                )
            )
            == 1
        )


def test_invalid_command_key_and_budget(signed_in):
    pid = signed_in.post("/api/projects", json={"prompt": "test app"}).json()[
        "project"
    ]["id"]
    assert (
        signed_in.post(
            f"/api/projects/{pid}/plan", headers={"Idempotency-Key": "x" * 129}
        ).status_code
        == 400
    )
    assert (
        signed_in.post(
            f"/api/projects/{pid}/race",
            json={"models": ["a", "b"], "budgetSeconds": 7141},
        ).status_code
        == 422
    )


def test_race_and_individual_retry_receipts(signed_in, monkeypatch):
    monkeypatch.setattr(orchestrator, "_race", waiting)
    pid = signed_in.post("/api/projects", json={"prompt": "race test"}).json()[
        "project"
    ]["id"]
    with session_scope() as s:
        s.get(Project, pid).status = "awaiting_approval"
    url = f"/api/projects/{pid}/race"
    headers = {"Idempotency-Key": "race-command"}
    first = signed_in.post(
        url, json={"models": ["one", "two"], "budgetSeconds": 360}, headers=headers
    )
    assert first.status_code == 200, first.text
    assert (
        signed_in.post(
            url, json={"models": ["one", "two"], "budgetSeconds": 360}, headers=headers
        ).json()
        == first.json()
    )
    signed_in.post(f"/api/projects/{pid}/cancel").raise_for_status()
    heat = first.json()["heats"][0]["id"]
    url += f"/{heat}/retry"
    headers = {"Idempotency-Key": "retry-command"}
    resumed = signed_in.post(url, json={"budgetSeconds": 600}, headers=headers)
    assert resumed.status_code == 200, resumed.text
    assert (
        signed_in.post(url, json={"budgetSeconds": 600}, headers=headers).json()
        == resumed.json()
    )
    assert (
        signed_in.post(url, json={"budgetSeconds": 180}, headers=headers).status_code
        == 409
    )
    signed_in.post(f"/api/projects/{pid}/cancel").raise_for_status()
    with session_scope() as s:
        assert len(list(s.scalars(select(Race).where(Race.project_id == pid)))) == 1
        s.get(RaceHeat, heat).status = "done"
    assert signed_in.post(url, json={"budgetSeconds": 360}).status_code == 409


def test_heat_continuation_retains_files_and_successful_sibling(signed_in):
    with session_scope() as s:
        user = s.scalar(select(User))
        uid = user.id
        project = Project(
            user_id=uid, title="race", prompt="game", status="awaiting_approval"
        )
        s.add(project)
        s.flush()
        pid = project.id
        race = Race(project_id=pid, status="done")
        s.add(race)
        s.flush()
        rid = race.id
        done = RaceHeat(
            race_id=rid, model="fast", status="done", position=0, input_tokens=19
        )
        failed = RaceHeat(
            race_id=rid,
            model="slow",
            status="timed_out",
            position=1,
            input_tokens=5,
            elapsed_ms=180000,
        )
        s.add_all([done, failed])
        s.flush()
        hid = failed.id
        done_id = done.id
    root = storage.workspace_dir(pid, hid)
    root.mkdir(parents=True)
    (root / "index.html").write_text("<html>preserved</html>")

    class Runtime:
        calls = []

        async def run(self, **kwargs):
            self.calls.append(kwargs)
            assert (root / "index.html").read_text() == "<html>preserved</html>"
            yield RuntimeLine(
                "result", None, {"resultText": "finished", "usage": {"inputTokens": 7}}
            )

    runtime = Runtime()

    async def scenario():
        o = Orchestrator(runtime)
        await o.start_race(pid, uid, rid, 360, hid)
        await o._jobs[pid]

    asyncio.run(scenario())
    assert len(runtime.calls) == 1 and runtime.calls[0]["gateway"].model == "slow"
    # Generation shares one deadline with repair attempts; setup time is
    # deducted rather than resetting the entire 360-second allowance.
    assert 359 <= runtime.calls[0]["budget_seconds"] <= 360
    with session_scope() as s:
        assert s.get(RaceHeat, done_id).input_tokens == 19
        heat = s.get(RaceHeat, hid)
        assert (
            heat.status == "done"
            and heat.input_tokens == 12
            and heat.elapsed_ms >= 180000
        )
        assert len(list(s.scalars(select(Run).where(Run.project_id == pid)))) == 1
        assert s.get(Project, pid).status == "awaiting_approval"
