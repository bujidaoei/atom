import asyncio
import json

import pytest
from sqlalchemy import select, text

from app import contract_history
from app.db import session_scope
from app.models import Project, Run, User, Message
from app.services.orchestrator import Orchestrator, _squad_context
from app.services.runtime_client import RuntimeLine
from test_contract_history import document


class PlanningRuntime:
    """Fault-injection double; these tests do not claim live model acceptance."""
    def __init__(self, failure=None):
        self.calls = []
        self.failure = failure
        self.count = 0

    async def run(self, **kwargs):
        self.calls.append(kwargs)
        if self.failure == 'wait':
            await asyncio.sleep(60)
        if self.failure == kwargs['role']:
            yield RuntimeLine('error', None, {'message': 'injected failure'})
            return
        if kwargs['role'] == 'emma':
            self.count += 1
            result = document(f'音效 {self.count}')
            result.pop('architecture'); result.pop('notes')
            output = json.dumps(result, ensure_ascii=False)
            if self.failure == 'invalid':
                output = '{"requirements":[]}'
        else:
            output = '使用 Web Audio 实现本版音效'
        yield RuntimeLine('result', None, {'resultText': output})

    async def cancel(self, _run_id):
        pass


def seed(client):
    pid = client.post('/api/projects', json={'prompt': '棋盘小游戏'}).json()['project']['id']
    with session_scope() as session:
        project = session.get(Project, pid)
        project.status = 'awaiting_approval'
        session.add(Message(project_id=pid, role='emma', content='旧版不做音效'))
        head = contract_history.commit_snapshot(session, pid, document(), expected=None, note='初始契约')
        return pid, project.user_id, head


def test_two_refinements_never_start_engineer_and_build_context_is_current(signed_in):
    pid, uid, head = seed(signed_in)
    runtime = PlanningRuntime()
    async def scenario():
        coordinator = Orchestrator(runtime)
        version = head['id']
        for message in ('增加落子音效', '再增加静音按钮'):
            await coordinator.start_refine(pid, uid, message, version)
            await coordinator._jobs[pid]
            with session_scope() as session:
                updated = contract_history.current(session, pid)
                assert updated['id'] != version
                assert session.get(Project, pid).status == 'awaiting_approval'
                version = updated['id']
        assert [call['role'] for call in runtime.calls] == ['emma', 'bob', 'emma', 'bob']
        assert '增加落子音效' in runtime.calls[2]['context']
    asyncio.run(scenario())
    context = _squad_context(pid)
    assert '旧版不做音效' not in context
    assert '增加落子音效' in context and '再增加静音按钮' in context


@pytest.mark.parametrize('failure', ['emma', 'bob', 'invalid', 'wait'])
def test_failed_or_cancelled_refinement_preserves_complete_head(signed_in, failure):
    pid, uid, head = seed(signed_in)
    async def scenario():
        coordinator = Orchestrator(PlanningRuntime(failure))
        await coordinator.start_refine(pid, uid, '增加音效', head['id'])
        if failure == 'wait':
            await asyncio.sleep(.02)
            await coordinator.cancel(pid)
        else:
            await coordinator._jobs[pid]
    asyncio.run(scenario())
    with session_scope() as session:
        assert contract_history.current(session, pid) == head
        assert session.get(Project, pid).status in ('error', 'cancelled')


def test_restore_route_replay_stale_and_project_isolation(signed_in):
    pid, uid, first = seed(signed_in)
    with session_scope() as session:
        second = contract_history.commit_snapshot(session, pid, document('音效'), expected=first['id'], note='音效')
    base = f'/api/projects/{pid}/contracts'
    response = signed_in.get(f'{base}/{first["id"]}')
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    payload = {'expectedVersion': second['id']}
    headers = {'Idempotency-Key': 'restore-test'}
    one = signed_in.post(f'{base}/{first["id"]}/restore', json=payload, headers=headers)
    two = signed_in.post(f'{base}/{first["id"]}/restore', json=payload, headers=headers)
    assert one.status_code == two.status_code == 200 and one.json() == two.json()
    assert signed_in.post(f'{base}/{first["id"]}/restore', json=payload).status_code == 409
    other, _, _ = seed(signed_in)
    assert signed_in.get(f'/api/projects/{other}/contracts/{first["id"]}').status_code == 404
    assert signed_in.post(f'/api/projects/{pid}/approve', json={'note': '未提交的音效'}).status_code == 422
    assert signed_in.post(f'/api/projects/{pid}/approve', json={'expectedVersion': first['id']}).status_code == 409
    assert signed_in.post(f'{base}/refine', json={'expectedVersion': one.json()['snapshot']['id'], 'message': '  '}).status_code == 422


def test_approval_persists_exact_snapshot_and_context(signed_in, monkeypatch):
    pid, uid, first = seed(signed_in)
    seen = []
    async def scenario():
        coordinator = Orchestrator(PlanningRuntime())
        async def build(_pid, _uid, _note, *, phase, binding):
            seen.append(binding['document'])
        monkeypatch.setattr(coordinator, '_build', build)
        job = await coordinator.start_build(pid, uid, None, expected_version=first['id'])
        await coordinator._jobs[pid]
        with session_scope() as session:
            assert session.execute(text('SELECT snapshot_id FROM contract_approvals WHERE job_id=:j'), {'j': job}).scalar() == first['id']
    asyncio.run(scenario())
    assert seen == [first['document']]


def test_other_owner_cannot_read_refine_or_restore(signed_in):
    pid, _, head = seed(signed_in)
    assert signed_in.post('/api/auth/logout').status_code == 200
    assert signed_in.post('/api/auth/register', json={'email': 'other-owner@example.com', 'password': 's3cretpass'}).status_code == 200
    root = f'/api/projects/{pid}/contracts'
    assert signed_in.get(root).status_code == 404
    assert signed_in.get(root + '/' + head['id']).status_code == 404
    assert signed_in.post(root + '/refine', json={'message': '增加音效', 'expectedVersion': head['id']}).status_code == 404
    assert signed_in.post(root + '/' + head['id'] + '/restore', json={'expectedVersion': head['id']}).status_code == 404
