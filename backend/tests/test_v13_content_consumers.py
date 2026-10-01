"""Verified v13 release consumption; worker-process authority is tested separately."""
from contextlib import contextmanager
import sqlite3

import pytest

from app.access_repository import AccessError
from app.content_access import ContentAccessRepository
from app.content_repository import ContentRepository
from app.migrations import verify
from app.release_repository import ReleaseRepository
from app.release_view import materialized_private_content
from app.verification_repository import VerificationError
from test_adoption_repository import Store, prepared, snapshot
from test_adoption_verification_repository import adopted
from test_revision_migrations import legacy
from test_verifier_authority import authorized, _intent, _register


@pytest.fixture
def published(authorized):
    path, receipt, request, authority, assignment, results = authorized
    _register(authority, assignment, results)
    payload, artifact = snapshot(b'<html>heat</html>')
    assert artifact == receipt.artifact
    store = Store(artifact.key, payload)
    intent = _intent(request)
    release = ReleaseRepository(path).publish_verified(store, **intent)
    assert verify(path) == 13
    return path, store, intent, release


def test_v13_public_binding_private_browser_session_and_source_revocation(published):
    path, store, intent, release = published
    content = ContentRepository(path)
    binding = content.bind(owner='user', project_id='project', release_id=release.release_id)
    assert content.sharing_binding(slug=intent['slug']) == binding
    assert content.resolve(binding_id=binding.id).revision_id == release.revision_id
    access = ContentAccessRepository(path)
    source = access.create_console_session(user_id='user', lifetime_seconds=900)
    bootstrap = access.bootstrap(binding_id=binding.id)
    detail = access.describe_handoff(viewer_id='user', source_session_id=source.id,
        binding_id=binding.id, challenge=bootstrap.challenge)
    assert detail['releaseId'] == release.release_id and detail['publicationGeneration'] == 1
    handoff = access.issue_handoff(viewer_id='user', source_session_id=source.id,
        binding_id=binding.id, challenge=bootstrap.challenge)
    session = access.exchange(binding_id=binding.id, handoff=handoff.secret,
        browser_nonce=bootstrap.secret)
    with pytest.raises(AccessError, match='content_access_denied'):
        access.exchange(binding_id=binding.id, handoff=handoff.secret,
            browser_nonce=bootstrap.secret)
    with materialized_private_content(content, access, store, binding_id=binding.id,
            session_secret=session.secret) as view:
        assert (view.path / 'index.html').read_bytes() == b'<html>heat</html>'
        assert view.publication.release_id == release.release_id
    with sqlite3.connect(path) as db:
        events = db.execute('SELECT event_kind,binding_id,source_session_id,publication_generation '
            "FROM security_audit_events WHERE event_kind LIKE 'content.%' ORDER BY sequence").fetchall()
        assert events == [
            ('content.handoff.issued',binding.id,source.id,1),
            ('content.session.created',binding.id,source.id,1),
        ]
        dump = '\n'.join(db.iterdump())
        assert all(secret not in dump for secret in
            (bootstrap.secret, handoff.secret, session.secret))
    successor = ReleaseRepository(path).publish_verified(store,
        **(intent | {'release_id': 'successor-release', 'expected_generation': 1}))
    assert successor.generation == 2
    assert content.resolve(binding_id=binding.id).release_id == release.release_id
    with pytest.raises(AccessError, match='content_access_denied'):
        access.authorize(binding_id=binding.id, session_secret=session.secret)
    second_bootstrap = access.bootstrap(binding_id=binding.id)
    second_handoff = access.issue_handoff(viewer_id='user', source_session_id=source.id,
        binding_id=binding.id, challenge=second_bootstrap.challenge)
    second_session = access.exchange(binding_id=binding.id, handoff=second_handoff.secret,
        browser_nonce=second_bootstrap.secret)
    assert access.authorize(binding_id=binding.id,
        session_secret=second_session.secret).publication_generation == 2
    access.revoke_console_session(user_id='user', session_id=source.id)
    with pytest.raises(AccessError, match='content_access_denied'):
        access.authorize(binding_id=binding.id, session_secret=second_session.secret)


def test_v13_private_release_and_unpublish_invalidate_pinned_access(authorized):
    path, receipt, request, authority, assignment, results = authorized
    _register(authority, assignment, results)
    payload, artifact = snapshot(b'<html>heat</html>')
    intent = _intent(request) | {'audience': 'owner'}
    release = ReleaseRepository(path).publish_verified(Store(artifact.key, payload), **intent)
    content = ContentRepository(path)
    binding = content.bind(owner='user', project_id='project', release_id=release.release_id)
    with pytest.raises(VerificationError, match='release_not_found'):
        content.resolve(binding_id=binding.id)
    with pytest.raises(VerificationError, match='content_not_found'):
        content.sharing_binding(slug=intent['slug'])
    assert content.resolve(binding_id=binding.id, viewer='user').release_id == release.release_id
    access = ContentAccessRepository(path)
    source = access.create_console_session(user_id='user', lifetime_seconds=900)
    bootstrap = access.bootstrap(binding_id=binding.id)
    handoff = access.issue_handoff(viewer_id='user', source_session_id=source.id,
        binding_id=binding.id, challenge=bootstrap.challenge)
    session = access.exchange(binding_id=binding.id, handoff=handoff.secret,
        browser_nonce=bootstrap.secret)
    ReleaseRepository(path).unpublish(owner='user', project_id='project', command_id='off',
        expected_release=release.release_id, expected_generation=release.generation)
    with pytest.raises(AccessError, match='content_access_denied'):
        access.authorize(binding_id=binding.id, session_secret=session.secret)
    with pytest.raises(VerificationError, match='release_not_found'):
        content.resolve(binding_id=binding.id, viewer='user')


@pytest.mark.parametrize('stage', ['issue', 'exchange'])
def test_v13_audit_failure_rolls_back_private_credential_transition(published, monkeypatch, stage):
    path, _, _, release = published
    binding = ContentRepository(path).bind(owner='user', project_id='project',
        release_id=release.release_id)
    access = ContentAccessRepository(path)
    source = access.create_console_session(user_id='user', lifetime_seconds=900)
    bootstrap = access.bootstrap(binding_id=binding.id)
    if stage == 'exchange':
        handoff = access.issue_handoff(viewer_id='user', source_session_id=source.id,
            binding_id=binding.id, challenge=bootstrap.challenge)
    original = access._transaction

    @contextmanager
    def deny_audit():
        with original() as db:
            db.set_authorizer(lambda action, table, *_: sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_INSERT and table == 'security_audit_events'
                else sqlite3.SQLITE_OK)
            yield db

    monkeypatch.setattr(access, '_transaction', deny_audit)
    with pytest.raises(AccessError, match='access_unavailable'):
        if stage == 'issue':
            access.issue_handoff(viewer_id='user', source_session_id=source.id,
                binding_id=binding.id, challenge=bootstrap.challenge)
        else:
            access.exchange(binding_id=binding.id, handoff=handoff.secret,
                browser_nonce=bootstrap.secret)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT consumed_at FROM content_bootstraps').fetchone() == (None,)
        assert db.execute('SELECT count(*) FROM content_sessions').fetchone() == (0,)
        if stage == 'issue':
            assert db.execute('SELECT count(*) FROM content_handoffs').fetchone() == (0,)
        else:
            assert db.execute('SELECT consumed_at FROM content_handoffs').fetchone() == (None,)
    monkeypatch.setattr(access, '_transaction', original)
    if stage == 'issue':
        handoff = access.issue_handoff(viewer_id='user', source_session_id=source.id,
            binding_id=binding.id, challenge=bootstrap.challenge)
    assert access.exchange(binding_id=binding.id, handoff=handoff.secret,
        browser_nonce=bootstrap.secret)
