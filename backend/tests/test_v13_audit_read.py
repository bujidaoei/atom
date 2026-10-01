"""Authorized audit reads across the verifier-era schema and archived history."""
import sqlite3

import pytest

from app.access_repository import AccessRepository
from app.audit_repository import AuditReadError, AuditRepository
from app.migrations import migrate, verify
from app.release_repository import ReleaseRepository
from test_adoption_repository import Store, prepared, snapshot
from test_adoption_verification_repository import adopted
from test_audit_archive_migration import authority
from test_audit_isolated_migration import isolated
from test_audit_pruning_migration import anchors, authorize, guarded
from test_revision_migrations import legacy
from test_verifier_authority import authorized, _intent, _register


def test_v13_actual_console_and_release_events_keep_scoped_frozen_pages(authorized):
    path, receipt, request, authority, assignment, results = authorized
    _register(authority, assignment, results)
    payload, artifact = snapshot(b'<html>heat</html>')
    assert artifact == receipt.artifact
    ReleaseRepository(path).publish_verified(Store(artifact.key, payload), **_intent(request))
    access = AccessRepository(path)
    source = access.create_console_session(user_id='user', lifetime_seconds=900)
    reader = AuditRepository(path)
    with sqlite3.connect(path) as db:
        before = list(db.iterdump())
    account = reader.page(user_id='user', source_session_id=source.id, limit=1)
    project = reader.page(user_id='user', source_session_id=source.id,
        project_id='project')
    assert [event['event_kind'] for event in account.events] == ['console.session.created']
    assert [event['event_kind'] for event in project.events] == ['release.published']
    assert account.archived == project.archived == ()
    with sqlite3.connect(path) as db:
        assert list(db.iterdump()) == before
    access.create_console_session(user_id='user', lifetime_seconds=900)
    assert len(reader.page(user_id='user', source_session_id=source.id,
        after=account.upper, upper=account.upper).events) == 0
    assert len(reader.page(user_id='user', source_session_id=source.id).events) == 2
    with pytest.raises(AuditReadError, match='audit_access_denied'):
        reader.page(user_id='user', source_session_id=source.id, project_id='foreign')
    with pytest.raises(AuditReadError, match='invalid_audit_page'):
        reader.page(user_id='user', source_session_id=source.id, limit=0)
    access.revoke_console_session(user_id='user', session_id=source.id)
    with pytest.raises(AuditReadError, match='audit_access_denied'):
        reader.page(user_id='user', source_session_id=source.id, upper=account.upper)


@pytest.mark.parametrize('target_version', [12, 13])
def test_v11_archived_identity_remains_in_one_page_window_after_migration(
        guarded, tmp_path, monkeypatch, target_version):
    path = guarded
    source_id = 'a' * 32
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('INSERT INTO console_sessions VALUES (?,?,?,?,NULL)',
            (source_id, 'user', 90, 200))
        db.execute("INSERT INTO security_audit_delivery(event_id,destination_id,state,next_attempt_at,delivered_at) "
                   "VALUES (?,'sink','delivered',100,101)", ('1' * 32,))
        authorize(db)
        anchors(db)
        db.execute('DELETE FROM security_audit_delivery')
        db.execute('DELETE FROM security_audit_events WHERE sequence=1')
    migrate(path, tmp_path / 'before-v12.db', target_version=12)
    if target_version == 13:
        migrate(path, tmp_path / 'before-v13.db', target_version=13)
    assert verify(path) == target_version
    monkeypatch.setattr('app.audit_repository.time.time', lambda: 100)
    monkeypatch.setattr('app.access_repository.time.time', lambda: 100)
    reader = AuditRepository(path)
    before = reader.page(user_id='user', source_session_id=source_id, limit=1)
    assert before.events == () and len(before.archived) == 1
    assert before.archived[0]['sequence'] == 1
    assert before.archived[0]['event_id'] == '1' * 32
    if target_version == 13:
        AccessRepository(path).create_console_session(user_id='user', lifetime_seconds=60)
        first = reader.page(user_id='user', source_session_id=source_id, limit=1)
        assert first.next_after == 1 and first.upper == 2
        next_page = reader.page(user_id='user', source_session_id=source_id,
            after=first.next_after, upper=first.upper, limit=1)
        assert next_page.archived == ()
        assert [event['event_kind'] for event in next_page.events] == ['console.session.created']
        assert next_page.next_after is None
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
