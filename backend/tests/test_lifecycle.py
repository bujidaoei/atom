import asyncio
import pytest

from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope
from app.events import EventBus
from app.models import Project, Run, User
from app.services.orchestrator import Orchestrator
from app.services.runtime_client import RuntimeLine


class ScriptedRuntime:
    def __init__(self, mode, reported_status=None):
        self.mode = mode
        self.reported_status = reported_status
        self.cancelled = []

    async def run(self, **kwargs):
        if self.mode == "silent":
            await asyncio.sleep(60)
        if self.mode == "error":
            raise ConnectionError("connection lost")
        if self.mode == "success":
            yield RuntimeLine("result", None, {"resultText": "ok"})
        if self.mode == "failed":
            yield RuntimeLine("error", None, {"message": "provider failed", 'status':self.reported_status})

    async def cancel(self, run_id):
        self.cancelled.append(run_id)


def seed():
    with session_scope() as session:
        user = session.scalar(select(User))
        project = Project(user_id=user.id, title="regression", prompt="calculator")
        session.add(project)
        session.flush()
        return project.id, user.id


def test_silent_deadline_is_terminal(signed_in, monkeypatch):
    monkeypatch.setattr(get_settings(), "build_budget_seconds", 0.05)
    project_id, user_id = seed()
    runtime = ScriptedRuntime("silent")

    async def scenario():
        o = Orchestrator(runtime)
        await o.start_build(project_id, user_id, None)
        await asyncio.wait_for(o._jobs[project_id], 1)
        assert not o.active(project_id)

    asyncio.run(scenario())
    with session_scope() as session:
        assert session.get(Project, project_id).status == "timed_out"
        run = session.scalar(select(Run).where(Run.project_id == project_id))
        assert run.status == "timed_out" and run.finished_at
    assert len(runtime.cancelled) == 1


@pytest.mark.parametrize('reported,expected', [('cancelled','cancelled'),('timed_out','timed_out'),
                                              ('done','failed'),(None,'failed'),({},'failed')])
@pytest.mark.parametrize('phase', ['plan','build'])
def test_runtime_error_status_cannot_claim_success(signed_in, reported, expected, phase):
    project_id,user_id=seed()
    async def scenario():
        runtime=ScriptedRuntime('failed',reported)
        orchestration=Orchestrator(runtime)
        if phase=='plan':
            await orchestration.start_plan(project_id,user_id)
        else:
            await orchestration.start_build(project_id,user_id,None)
        await orchestration._jobs[project_id]
        assert len(runtime.cancelled)==1
    asyncio.run(scenario())
    with session_scope() as session:
        run=session.scalar(select(Run).where(Run.project_id==project_id))
        assert run.status==expected and run.finished_at is not None
        assert session.get(Project,project_id).status==('error' if expected=='failed' else expected)


def test_cancel_is_durable_and_idempotent(signed_in):
    project_id, user_id = seed()
    runtime = ScriptedRuntime("silent")

    async def scenario():
        o = Orchestrator(runtime)
        await o.start_build(project_id, user_id, None)
        await asyncio.sleep(0.05)
        await o.cancel(project_id)
        await o.cancel(project_id)
        assert not o.active(project_id)

    asyncio.run(scenario())
    with session_scope() as session:
        assert session.get(Project, project_id).status == "cancelled"
        assert session.get(Project, project_id).active_run_id is None
        assert all(
            r.status != "running" and r.finished_at
            for r in session.scalars(select(Run))
        )


def test_empty_stream_cannot_complete(signed_in):
    project_id, user_id = seed()

    async def scenario():
        o = Orchestrator(ScriptedRuntime("empty"))
        await o.start_build(project_id, user_id, None)
        await o._jobs[project_id]

    asyncio.run(scenario())
    with session_scope() as session:
        assert session.get(Project, project_id).status == "error"
        assert session.scalar(select(Run)).status == "failed"


def test_restart_reconciles_orphan(signed_in):
    project_id, _ = seed()
    with session_scope() as session:
        project = session.get(Project, project_id)
        run = Run(project_id=project_id, role="alex", model="test", status="running")
        session.add(run)
        session.flush()
        project.status = "building"
        project.active_run_id = run.id
    asyncio.run(Orchestrator(ScriptedRuntime("empty")).reconcile())
    with session_scope() as session:
        assert session.get(Project, project_id).status == "interrupted"
        assert session.scalar(select(Run)).status == "interrupted"


def test_concurrent_events_are_ordered(signed_in):
    project_id, _ = seed()

    async def scenario():
        bus = EventBus()
        queue = await bus.subscribe(project_id)
        await asyncio.gather(
            *(bus.publish(project_id, "test", {"n": n}) for n in range(30))
        )
        seqs = [queue.get_nowait().seq for _ in range(30)]
        assert seqs == list(range(1, 31))

    asyncio.run(scenario())


def test_cancel_before_job_starts(signed_in):
    pid, uid = seed()

    async def scenario():
        o = Orchestrator(ScriptedRuntime("silent"))
        await o.start_build(pid, uid, None)
        await o.cancel(pid)
        assert not o.active(pid)

    asyncio.run(scenario())
    with session_scope() as session:
        assert session.get(Project, pid).status == "cancelled"


def test_race_all_fail_and_cancellation_converge(signed_in):
    from app.models import Race, RaceHeat

    pid, uid = seed()

    async def scenario():
        o = Orchestrator(ScriptedRuntime("failed"))
        rid = o.create_race(pid, ["one", "two"])
        await o.start_race(pid, uid, rid)
        await o._jobs[pid]
        with session_scope() as session:
            assert session.get(Race, rid).status == "failed"
            assert all(
                h.status == "failed" and h.run_id
                for h in session.scalars(select(RaceHeat))
            )
        o = Orchestrator(ScriptedRuntime("silent"))
        rid = o.create_race(pid, ["one", "two"])
        await o.start_race(pid, uid, rid)
        await asyncio.sleep(0.05)
        from app import storage

        with session_scope() as session:
            heat_id = session.scalar(select(RaceHeat.id).where(RaceHeat.race_id == rid))
        workspace = storage.workspace_dir(pid, heat_id)
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "index.html").write_text("partial output")
        await asyncio.gather(o.cancel(pid), o.cancel(pid))
        with session_scope() as session:
            assert session.get(Race, rid).status == "cancelled"
            assert session.get(RaceHeat, heat_id).file_count == 1
            assert session.get(RaceHeat, heat_id).bytes == len("partial output")
            assert all(
                h.status not in {"running", "queued"}
                for h in session.scalars(select(RaceHeat))
            )

    asyncio.run(scenario())


def test_failed_mike_stops_planning(signed_in):
    pid, uid = seed()

    async def scenario():
        o = Orchestrator(ScriptedRuntime("failed"))
        await o.start_plan(pid, uid)
        await o._jobs[pid]

    asyncio.run(scenario())
    with session_scope() as session:
        assert [r.role for r in session.scalars(select(Run))] == ["mike"]
        assert session.get(Project, pid).status == "error"


def test_queue_overflow_forces_replay(signed_in):
    pid, _ = seed()

    async def scenario():
        bus = EventBus()
        q = await bus.subscribe(pid)
        q._maxsize = 2
        for n in range(3):
            await bus.publish(pid, "test", {"n": n})
        assert q.get_nowait().type == "stream.resync"
        assert [e.seq for e in bus.replay(pid, 0)] == [1, 2, 3]

    asyncio.run(scenario())
