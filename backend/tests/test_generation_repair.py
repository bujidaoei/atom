"""Real Node validation and persisted runs with deterministic runtime fault injection."""
import asyncio

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope
from app.models import Message, Project, Run
from app.services.orchestrator import Orchestrator
from app.services.runtime_client import RuntimeLine
from test_lifecycle import seed


class GeneratedFiles:
    def __init__(self, mode='repair'):
        self.mode, self.calls, self.cancelled = mode, [], []

    async def run(self, **args):
        self.calls.append(args)
        if self.mode == 'infrastructure':
            raise ConnectionError('provider disconnected')
        root = args['workspace_path']
        (root / 'index.html').write_text('<script src="app.js"></script>', encoding='utf-8')
        invalid = len(self.calls) == 1 or self.mode == 'exhaust'
        (root / 'app.js').write_text('return moves;\n}' if invalid else 'const moves = [];', encoding='utf-8')
        yield RuntimeLine('result', None, {'resultText': '已完成全部功能',
            'usage': {'inputTokens': 11, 'outputTokens': 7}})

    async def cancel(self, run_id):
        self.cancelled.append(run_id)


@pytest.mark.parametrize('mode, count, status', [('repair', 2, 'ready'), ('exhaust', 3, 'error'),
                                              ('infrastructure', 1, 'error')])
def test_generation_repairs_only_artifact_failures_with_bounded_audited_runs(signed_in, mode, count, status):
    project_id, owner = seed()
    runtime = GeneratedFiles(mode)
    async def run():
        coordinator = Orchestrator(runtime)
        await coordinator.start_build(project_id, owner, None)
        await coordinator._jobs[project_id]
    asyncio.run(run())
    assert len(runtime.calls) == count
    with session_scope() as db:
        project = db.get(Project, project_id)
        runs = list(db.scalars(select(Run).where(Run.project_id == project_id).order_by(Run.started_at)))
        messages = list(db.scalars(select(Message).where(Message.project_id == project_id)))
        assert project.status == status and project.active_run_id is None
        assert len(runs) == count and all(row.finished_at for row in runs)
        for row in runs:
            if row.error and '语法' in row.error:
                assert 'app.js:2' in row.error and 'SyntaxError' in row.error
                assert str(runtime.calls[0]['workspace_path']) not in row.error
                assert 'node:internal' not in row.error
        for message in messages:
            row = next((r for r in runs if r.id == message.run_id), None)
            if row and row.status != 'done':
                assert message.content != '已完成全部功能'
        if mode != 'infrastructure':
            assert sum(r.input_tokens for r in runs) == count * 11
            assert sum(r.output_tokens for r in runs) == count * 7
    if count > 1:
        assert 'app.js:2' in runtime.calls[1]['prompt']
        assert runtime.calls[1]['budget_seconds'] < runtime.calls[0]['budget_seconds']


def test_repair_can_be_disabled(signed_in, monkeypatch):
    monkeypatch.setattr(get_settings(), 'generation_repair_attempts', 0)
    project_id, owner = seed()
    runtime = GeneratedFiles()
    async def run():
        coordinator = Orchestrator(runtime)
        await coordinator.start_build(project_id, owner, None)
        await coordinator._jobs[project_id]
    asyncio.run(run())
    assert len(runtime.calls) == 1


class WaitingRepair(GeneratedFiles):
    async def run(self, **args):
        if self.calls:
            self.calls.append(args)
            await asyncio.sleep(60)
        else:
            async for item in super().run(**args):
                yield item


@pytest.mark.parametrize('cancel', [True, False])
def test_repair_cancellation_and_shared_deadline_are_terminal(signed_in, monkeypatch, cancel):
    monkeypatch.setattr(get_settings(), 'build_budget_seconds', 3 if cancel else .5)
    runtime = WaitingRepair()
    project_id, owner = seed()
    async def scenario():
        coordinator = Orchestrator(runtime)
        await coordinator.start_build(project_id, owner, None)
        if cancel:
            for _ in range(200):
                if len(runtime.calls) == 2:
                    break
                await asyncio.sleep(.01)
            assert len(runtime.calls) == 2
            await coordinator.cancel(project_id)
        else:
            await asyncio.wait_for(coordinator._jobs[project_id], 3)
    asyncio.run(scenario())
    assert len(runtime.calls) == 2
    terminal = 'cancelled' if cancel else 'timed_out'
    with session_scope() as db:
        assert db.get(Project, project_id).status == terminal
        runs = list(db.scalars(select(Run).where(Run.project_id == project_id).order_by(Run.started_at)))
        assert [r.status for r in runs] == ['failed', terminal]
        assert all(r.finished_at for r in runs)
        assert sum(r.input_tokens for r in runs) == 11
    assert len(runtime.cancelled) == 2
    assert runtime.calls[1]['budget_seconds'] < runtime.calls[0]['budget_seconds']
