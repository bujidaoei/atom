"""Retained owner snapshots preserve source authorization and revocation fences."""
import pytest

from app.access_repository import AccessError
from app.audit_repository import AuditRepository
from app.audit_governance import AuditGovernanceRepository
from app.audit_delivery import AuditDeliveryRepository
from app.content_access import ContentAccessRepository
from app.content_repository import ContentRepository
from app.migrations import migrate
from app.release_repository import ReleaseRepository
from app.release_view import materialized_private_content
from app.verification_repository import VerificationError
from test_adoption_repository import prepared
from test_adoption_verification_repository import adopted
from test_revision_migrations import legacy
from test_verifier_authority import authorized
from test_v13_content_consumers import (
    published,
    test_v13_public_binding_private_browser_session_and_source_revocation as _public_access,
    test_v13_audit_failure_rolls_back_private_credential_transition as _audit_failure,
)


@pytest.fixture
def retained(published, tmp_path):
    for version in (14, 15, 16):
        migrate(published[0], tmp_path / f'before-{version}.db', target_version=version)
    return published


def test_v16_public_access_audit_and_source_revocation(retained):
    _public_access(retained)


@pytest.mark.parametrize('stage', ['issue', 'exchange'])
def test_v16_audit_failure_is_atomic(retained, monkeypatch, stage):
    _audit_failure(retained, monkeypatch, stage)


def test_v16_audit_read_and_delivery_preserve_owner_source(retained):
    path, _, _, _ = retained
    access = ContentAccessRepository(path)
    source = access.create_console_session(user_id='user', lifetime_seconds=900)
    page = AuditRepository(path).page(user_id='user', source_session_id=source.id)
    assert any(event['event_kind'] == 'console.session.created' for event in page.events)
    AuditGovernanceRepository(path).execute(command_id='register', operator_id='operator',
        destination_id='sink', scope_kind='account', scope_id='user',
        action='register', expected_generation=0)
    delivery = AuditDeliveryRepository(path, destination_id='sink', scope_kind='account', scope_id='user')
    assert delivery.enroll()['added'] >= 1
    lease = delivery.claim(limit=100)
    delivery.acknowledge(event_ids=[event['event_id'] for event in lease.events], lease_owner=lease.owner)
    assert delivery.status()['delivered'] == len(lease.events)


def test_withdrawn_snapshot_requires_fresh_owner_authority(retained):
    path, store, intent, release = retained
    content = ContentRepository(path)
    binding = content.bind(owner='user', project_id='project', release_id=release.release_id)
    access = ContentAccessRepository(path)
    source = access.create_console_session(user_id='user', lifetime_seconds=900)

    def session():
        bootstrap = access.bootstrap(binding_id=binding.id)
        handoff = access.issue_handoff(viewer_id='user', source_session_id=source.id,
            binding_id=binding.id, challenge=bootstrap.challenge)
        return access.exchange(binding_id=binding.id, handoff=handoff.secret,
            browser_nonce=bootstrap.secret)

    old = session()
    ReleaseRepository(path).unpublish(owner='user', project_id='project', command_id='withdraw',
        expected_release=release.release_id, expected_generation=release.generation)
    with pytest.raises(AccessError, match='content_access_denied'):
        access.authorize(binding_id=binding.id, session_secret=old.secret)
    for viewer in (None, 'foreign'):
        with pytest.raises(VerificationError, match='release_not_found'):
            content.resolve(binding_id=binding.id, viewer=viewer)
    with pytest.raises(VerificationError, match='content_not_found'):
        content.sharing_binding(slug=intent['slug'])
    bootstrap = access.bootstrap(binding_id=binding.id)
    with pytest.raises(AccessError, match='content_access_denied'):
        access.issue_handoff(viewer_id='foreign', source_session_id=source.id,
            binding_id=binding.id, challenge=bootstrap.challenge)
    fresh = session()
    with materialized_private_content(content, access, store, binding_id=binding.id,
            session_secret=fresh.secret) as view:
        assert view.publication.release_id == release.release_id
        assert (view.path / 'index.html').read_bytes() == b'<html>heat</html>'
    access.revoke_console_session(user_id='user', session_id=source.id)
    with pytest.raises(AccessError, match='content_access_denied'):
        access.authorize(binding_id=binding.id, session_secret=fresh.secret)
