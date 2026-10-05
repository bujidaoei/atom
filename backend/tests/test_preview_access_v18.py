"""Real SQLite preview-capability migration, scope and rollback evidence."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.access_repository import AccessRepository
from app.artifacts import ArtifactError
from app.audit_repository import AuditRepository
from app.content_repository import ContentRepository
from app.migrations import MigrationError, migrate, verify, verify_backup
from app.project_origins import ProjectOriginRepository
from app.preview_access import PreviewAccessError, PreviewAccessRepository
from app.preview_view import materialized_preview
from app.release_repository import ReleaseRepository
from app.revisions import RevisionRepository
from app.verification_repository import VerificationRepository
from test_adoption_repository import Store, prepared
from test_adoption_verification_repository import adopted
from test_revision_migrations import legacy
from test_rollback_v14_repository import historical
from test_v13_content_consumers import published
from test_verifier_authority import authorized


@pytest.fixture
def v17(legacy, tmp_path):
    path, _ = legacy
    for version in range(11, 18):
        migrate(path, tmp_path / f'before-v{version}.db', target_version=version)
    assert verify(path) == 17
    return path


def test_v18_migration_is_additive_idempotent_and_backed_up(v17, tmp_path):
    backup = tmp_path / 'before-v18.db'
    result = migrate(v17, backup, target_version=18)
    assert result.applied and result.version == verify(v17) == 18
    assert result.backup_sha256 == verify_backup(backup, expected_version=17)
    assert not migrate(v17, tmp_path / 'unused-replay.db', target_version=18).applied
    with sqlite3.connect(v17) as db:
        assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        for table in ('preview_handoffs', 'preview_sessions', 'preview_audit_events'):
            assert db.execute(f'SELECT count(*) FROM {table}').fetchone() == (0,)


def test_v18_failure_preserves_exact_v17_and_verified_backup(v17, tmp_path, monkeypatch):
    from app.migrations import preview_access_v18

    actual = preview_access_v18.apply

    def fail(db):
        actual(db)
        raise sqlite3.OperationalError('injected before commit')

    monkeypatch.setattr(preview_access_v18, 'apply', fail)
    backup = tmp_path / 'failed-v18.db'
    with pytest.raises(MigrationError, match='migration_failed'):
        migrate(v17, backup, target_version=18)
    assert verify(v17) == 17
    assert verify_backup(backup, expected_version=17)


def test_v18_grants_and_sessions_require_matching_project_revision_and_source(historical, tmp_path):
    path, _store, _intent, _source, _displaced = historical
    for version in range(15, 19):
        migrate(path, tmp_path / f'before-v{version}.db', target_version=version)
    ProjectOriginRepository(path, first_port=20000, last_port=20003).reserve('project')
    source = AccessRepository(path).create_console_session(user_id='user', lifetime_seconds=900)
    current = ReleaseRepository(path, required_schema=16).current(owner='user', project_id='project')
    assert current is not None
    assert ContentRepository(path).resolve(binding_id=current.binding_id, viewer='user').release_id == current.release_id
    assert RevisionRepository(path).path == path
    assert VerificationRepository(path).path == path
    assert AuditRepository(path).path == path
    with sqlite3.connect(path) as db:
        revision = db.execute('SELECT id FROM revision_records WHERE project_id=? LIMIT 1',
                              ('project',)).fetchone()[0]
        grant = ('a' * 64, 'project', revision, 'user', source.id, 100, 160, None)
        db.execute('INSERT INTO preview_handoffs VALUES (?,?,?,?,?,?,?,?)', grant)
        with pytest.raises(sqlite3.IntegrityError, match='invalid_preview_scope'):
            db.execute('INSERT INTO preview_handoffs VALUES (?,?,?,?,?,?,?,?)',
                       ('b' * 64, 'project', 'not-a-revision', 'user', source.id, 100, 160, None))
        with pytest.raises(sqlite3.IntegrityError, match='immutable_preview_handoff'):
            db.execute("UPDATE preview_handoffs SET revision_id='other' WHERE token_hash=?", ('a' * 64,))
        db.execute('UPDATE preview_handoffs SET consumed_at=110 WHERE token_hash=?', ('a' * 64,))
        with pytest.raises(sqlite3.IntegrityError, match='immutable_preview_handoff'):
            db.execute('UPDATE preview_handoffs SET consumed_at=111 WHERE token_hash=?', ('a' * 64,))
        db.execute('INSERT INTO preview_sessions VALUES (?,?,?,?,?,?,?,?,?)',
                   ('c' * 64, 'a' * 64, 'project', revision, 'user', source.id, 110, 200, None))
        with pytest.raises(sqlite3.IntegrityError, match='invalid_preview_session'):
            db.execute('INSERT INTO preview_sessions VALUES (?,?,?,?,?,?,?,?,?)',
                       ('d' * 64, 'b' * 64, 'project', revision, 'user', source.id, 110, 200, None))
        db.execute('UPDATE preview_sessions SET revoked_at=120 WHERE token_hash=?', ('c' * 64,))
        with pytest.raises(sqlite3.IntegrityError, match='immutable_preview_session'):
            db.execute('UPDATE preview_sessions SET revoked_at=121 WHERE token_hash=?', ('c' * 64,))


def test_owner_preview_handoff_is_one_use_project_bound_and_revoked_on_logout(historical, tmp_path):
    path, store, _intent, _source, _displaced = historical
    for version in range(15, 19):
        migrate(path, tmp_path / f'before-v{version}.db', target_version=version)
    with sqlite3.connect(path) as db:
        revision = db.execute('SELECT revision_id FROM release_records WHERE project_id=? LIMIT 1',
                              ('project',)).fetchone()[0]
    source = AccessRepository(path).create_console_session(user_id='user', lifetime_seconds=900)
    access = PreviewAccessRepository(path)
    request = dict(owner_id='user', source_session_id=source.id,
                   project_id='project', revision_id=revision)
    with pytest.raises(PreviewAccessError, match='preview_origin_required'):
        access.issue(**request)
    ProjectOriginRepository(path, first_port=20000, last_port=20003).reserve('project')
    with pytest.raises(PreviewAccessError, match='preview_access_denied'):
        access.issue(**(request | {'owner_id': 'foreign'}))
    grant = access.issue(**request)
    assert grant.project_id == 'project' and grant.revision_id == revision
    with sqlite3.connect(path) as db:
        dump = '\n'.join(db.iterdump())
        assert grant.secret not in dump
    with pytest.raises(PreviewAccessError, match='preview_access_denied'):
        access.exchange(project_id='other', handoff=grant.secret)
    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = list(pool.map(lambda _: _exchange_result(access, grant.secret), range(2)))
    assert sorted(kind for kind, _ in attempts) == ['denied', 'ok']
    session = next(value for kind, value in attempts if kind == 'ok')
    assert access.authorize(project_id='project', session_secret=session.secret).revision_id == revision
    with materialized_preview(access, store, project_id='project', session_secret=session.secret) as view:
        assert (view.path / 'index.html').read_bytes() == b'<html>heat</html>'
        assert view.revision.revision_id == revision
    with pytest.raises(ArtifactError, match='preview_artifact_mismatch'):
        with materialized_preview(access, _CorruptStore(), project_id='project',
                                  session_secret=session.secret):
            pass
    with pytest.raises(PreviewAccessError, match='preview_access_denied'):
        access.authorize(project_id='other', session_secret=session.secret)
    with sqlite3.connect(path) as db:
        dump = '\n'.join(db.iterdump())
        assert grant.secret not in dump and session.secret not in dump
        assert db.execute('SELECT event_kind FROM preview_audit_events ORDER BY sequence').fetchall() == [
            ('preview.handoff.issued',), ('preview.session.created',)]
        with pytest.raises(sqlite3.IntegrityError, match='immutable_preview_audit'):
            db.execute('DELETE FROM preview_audit_events')
    AccessRepository(path).revoke_console_session(user_id='user', session_id=source.id)
    with pytest.raises(PreviewAccessError, match='preview_access_denied'):
        access.authorize(project_id='project', session_secret=session.secret)


@pytest.mark.parametrize('prepared', [12], indirect=True)
def test_current_saved_race_heat_opens_on_isolated_preview_origin(prepared, tmp_path):
    path, _main, _heat, heat_payload, heat_artifact = prepared
    for version in range(13, 19):
        migrate(path, tmp_path / f'before-v{version}.db', target_version=version)
    ProjectOriginRepository(path, first_port=20000, last_port=20003).reserve('project')
    source = AccessRepository(path).create_console_session(user_id='user', lifetime_seconds=900)
    access = PreviewAccessRepository(path)
    grant = access.issue(owner_id='user', source_session_id=source.id,
                         project_id='project', revision_id='heat-root')
    session = access.exchange(project_id='project', handoff=grant.secret)
    with materialized_preview(access, Store(heat_artifact.key, heat_payload),
                              project_id='project', session_secret=session.secret) as view:
        assert view.revision.revision_id == 'heat-root'
        assert (view.path / 'index.html').read_bytes() == b'<html>heat</html>'


def _exchange_result(access, handoff):
    try:
        return 'ok', access.exchange(project_id='project', handoff=handoff)
    except PreviewAccessError as error:
        assert str(error) == 'preview_access_denied'
        return 'denied', None


class _CorruptStore:
    def read(self, _key):
        return b'not an Atom snapshot'
