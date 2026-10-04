import json
import sqlite3

import pytest
from sqlalchemy import text

from app.db import session_scope
from app.models import Project
from app.contract_history import current, commit_snapshot, history, restore, snapshot, ContractConflict


def document(title='棋盘'):
    return {'requirements': [{'key': 'board', 'title': title, 'detail': title,
                             'checks': [{'type': 'exists', 'selector': '#board'}]}],
            'scope': [title], 'outOfScope': [], 'architecture': 'HTML', 'notes': []}


def test_full_restore_preserves_history_and_rejects_stale(signed_in):
    project_id = signed_in.post('/api/projects', json={'prompt': '象棋游戏'}).json()['project']['id']
    with session_scope() as session:
        first = commit_snapshot(session, project_id, document(), expected=None, note='初始契约')
    with session_scope() as session:
        second = commit_snapshot(session, project_id, document('棋盘音效'), expected=first['id'], note='增加音效')
    with session_scope() as session:
        assert snapshot(session, project_id, first['id'])['document'] == document()
        assert current(session, project_id)['id'] == second['id']
        restored = restore(session, project_id, first['id'], expected=second['id'])
        assert restored['document'] == first['document']
        assert restored['version'] == 3 and restored['sourceId'] == first['id']
    with session_scope() as session:
        assert len(history(session, project_id)['items']) == 3
        assert session.get(Project, project_id).status == 'awaiting_approval'
        with pytest.raises(ContractConflict):
            restore(session, project_id, first['id'], expected=second['id'])


def test_snapshot_is_project_scoped_immutable_and_validated(signed_in):
    one, two = [signed_in.post('/api/projects', json={'prompt': title}).json()['project']['id'] for title in ('棋盘项目', '另一个项目')]
    with session_scope() as session:
        first = commit_snapshot(session, one, document(), expected=None, note='初始契约')
    with session_scope() as session:
        assert snapshot(session, two, first['id']) is None
        with pytest.raises(Exception, match='immutable_contract'):
            session.execute(text('UPDATE contract_snapshots SET note=:note WHERE id=:id'), {'note': 'bad', 'id': first['id']})
    with session_scope() as session:
        invalid = document()
        invalid['requirements'][0]['checks'] = []
        with pytest.raises(ValueError):
            commit_snapshot(session, one, invalid, expected=first['id'], note='invalid')
        assert current(session, one)['id'] == first['id']


def test_history_pagination(signed_in):
    project_id = signed_in.post('/api/projects', json={'prompt': '分页项目'}).json()['project']['id']
    expected = None
    for index in range(23):
        with session_scope() as session:
            expected = commit_snapshot(session, project_id, document(), expected=expected, note=str(index))['id']
    with session_scope() as session:
        page = history(session, project_id)
        assert len(page['items']) == 20 and 'document' not in page['items'][0]
        older = history(session, project_id, before=page['nextCursor'])
        assert [item['version'] for item in older['items']] == [3, 2, 1]
        assert older['nextCursor'] is None
