"""Transactional contract history. Caller owns commit/rollback and owner admission."""
from datetime import datetime, timezone
import json

from sqlalchemy import select, text, inspect

from .models import Message, Project, Requirement, new_id
from .verification_contract import capture_contract


class ContractConflict(ValueError):
    pass


def available(session):
    return inspect(session.connection()).has_table('contract_snapshots')


def validate_document(document):
    if not isinstance(document, dict) or set(document) != {'requirements', 'scope', 'outOfScope', 'architecture', 'notes'}:
        raise ValueError('契约结构不完整，请重新微调')
    capture_contract(document['requirements'])
    for field in ('scope', 'outOfScope', 'notes'):
        value = document[field]
        if not isinstance(value, list) or len(value) > 256 or any(not isinstance(s, str) or len(s) > 4000 for s in value):
            raise ValueError('契约说明无效或过长')
    if not isinstance(document['architecture'], str) or len(document['architecture']) > 60000:
        raise ValueError('契约设计说明无效或过长')
    raw = json.dumps(document, ensure_ascii=False, allow_nan=False)
    if len(raw.encode()) > 1_048_576:
        raise ValueError('契约内容过长')
    return raw


def _view(row, *, full=True):
    if row is None:
        return None
    result = {'id': row['id'], 'version': row['version'], 'note': row['note'],
              'sourceId': row['source_id'], 'createdAt': row['created_at']}
    if full:
        result['document'] = json.loads(row['document_json'])
    return result


def current(session, project_id):
    return _view(session.execute(text('SELECT * FROM contract_snapshots WHERE project_id=:p ORDER BY version DESC LIMIT 1'), {'p': project_id}).mappings().first())


def snapshot(session, project_id, snapshot_id):
    return _view(session.execute(text('SELECT * FROM contract_snapshots WHERE project_id=:p AND id=:id'), {'p': project_id, 'id': snapshot_id}).mappings().first())


def history(session, project_id, *, before=None):
    head = current(session, project_id)
    rows = list(session.execute(text('SELECT id,version,note,source_id,created_at FROM contract_snapshots '
        'WHERE project_id=:p AND (:before IS NULL OR version<:before) ORDER BY version DESC LIMIT 21'),
        {'p': project_id, 'before': before}).mappings())
    return {'currentId': head['id'] if head else None, 'items': [_view(row, full=False) for row in rows[:20]],
            'nextCursor': rows[19]['version'] if len(rows) > 20 else None}


def lock(session):
    # SQLAlchemy autobegin does not begin a SQLite transaction on SELECT.
    # Acquire the writer before reading the head, never upgrade a stale read.
    connection = session.connection().connection.driver_connection
    if not connection.in_transaction:
        session.execute(text('BEGIN IMMEDIATE'))


def require_head(session, project_id, expected):
    head = current(session, project_id)
    if (head['id'] if head else None) != expected:
        raise ContractConflict('契约已更新，请刷新后查看最新版本再操作')
    return head


def commit_snapshot(session, project_id, document, *, expected, note, source_id=None):
    raw = validate_document(document)
    lock(session)
    head = require_head(session, project_id, expected)
    identifier, version = new_id(), (head['version'] + 1 if head else 1)
    session.execute(text('INSERT INTO contract_snapshots VALUES (:id,:p,:v,:doc,:note,:source,:time)'),
                    {'id': identifier, 'p': project_id, 'v': version, 'doc': raw, 'note': note,
                     'source': source_id, 'time': datetime.now(timezone.utc).isoformat()})
    for existing in session.scalars(select(Requirement).where(Requirement.project_id == project_id)):
        session.delete(existing)
    session.flush()
    for position, item in enumerate(document['requirements']):
        session.add(Requirement(project_id=project_id, key=item['key'], title=item['title'], detail=item['detail'],
                                checks_json=json.dumps(item['checks'], ensure_ascii=False), position=position))
    session.flush()
    return snapshot(session, project_id, identifier)


def ensure_baseline(session, project_id):
    lock(session)
    head = current(session, project_id)
    if head:
        return head
    rows = session.scalars(select(Requirement).where(Requirement.project_id == project_id).order_by(Requirement.position)).all()
    if not rows:
        return None
    # Old versions only persisted rendered planning prose; retain it explicitly,
    # without claiming to have reconstructed the original JSON or past history.
    latest = {}
    for message in session.scalars(select(Message).where(Message.project_id == project_id,
            Message.role.in_(('iris', 'emma', 'bob'))).order_by(Message.created_at)):
        latest[message.role] = message.content
    document = {'requirements': [{'key': r.key, 'title': r.title, 'detail': r.detail, 'checks': json.loads(r.checks_json)} for r in rows],
                'scope': [], 'outOfScope': [], 'notes': [],
                'architecture': '\n\n'.join(f'{role}: {content}' for role, content in latest.items())}
    return commit_snapshot(session, project_id, document, expected=None, note='已有契约（历史起点）')


def restore(session, project_id, source_id, *, expected):
    lock(session)
    source = snapshot(session, project_id, source_id)
    if source is None:
        raise LookupError('契约版本不存在')
    result = commit_snapshot(session, project_id, source['document'], expected=expected,
                             note=f"恢复版本 {source['version']}", source_id=source_id)
    project = session.get(Project, project_id)
    project.status = 'awaiting_approval'
    return result


def build_context(document):
    return ('以下为用户当前确认的完整契约，优先于原始想法和任何历史对话。仅按此版本执行。\n'
            + json.dumps(document, ensure_ascii=False))
