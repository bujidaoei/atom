"""Real Linux store and v13 internal verifier-to-release evidence path."""
import json
import sqlite3
import sys

import pytest

from app.adoption_repository import AdoptionRepository
from app.artifacts import ArtifactError, ArtifactStore
from app.content_access import ContentAccessRepository
from app.content_repository import ContentRepository
from app.migrations import migrate, verify
from app.release_repository import ReleaseRepository
from app.release_view import materialized_private_content
from app.verification_contract import capture_contract
from app.verification_repository import VerificationRepository
from app.verifier_authority import VerifierAuthority
from test_adoption_repository import adopt, prepared
from test_revision_migrations import legacy


@pytest.mark.skipif(sys.platform != 'linux', reason='ArtifactStore requires Linux filesystem semantics')
def test_real_artifact_requires_registered_v13_attestation(prepared, tmp_path):
    path, main, _, payload, artifact = prepared
    root = tmp_path / 'artifacts'
    root.mkdir(mode=0o700)
    store = ArtifactStore(root)
    assert store.put(payload) == artifact
    adopted = adopt(AdoptionRepository(path), store)
    requirement = {'key': 'page', 'title': 'Page', 'detail': '',
        'checks': [{'type': 'exists', 'selector': '#page'}]}
    with sqlite3.connect(path) as db:
        db.execute('INSERT INTO requirements VALUES (?,?,?,?,?,?,?)',
            ('requirement','project','page','Page','',json.dumps(requirement['checks']),0))
    migrate(path, tmp_path / 'pre-v13.db', target_version=13)
    request = VerificationRepository(path).reserve(owner='user', workspace_id=main,
        request_id='real-store-verify', expected_revision=adopted.revision_id,
        expected_contract=capture_contract([requirement]).digest,
        policy_digest='c' * 64, runner_version='runner-1', budget_seconds=60)
    authority = VerifierAuthority(path)
    assignment = authority.dispatch(owner='user', request_id=request.id,
        artifact=artifact, route_id='a' * 32, verifier_id='worker-1',
        environment_digest='e' * 64)
    authority.register(request_id=request.id, route_id=assignment.route_id,
        verifier_id=assignment.verifier_id,
        environment_digest=assignment.environment_digest, artifact=artifact,
        credential=assignment.credential,
        results=[{'key':'page','checkIndex':0,'passed':True,'note':'observed'}])
    intent = dict(owner='user',project_id='project',release_id='real-store-release',
        verification_id=request.id,expected_revision=adopted.revision_id,
        expected_generation=0,policy_digest='c' * 64,runner_version='runner-1',
        audience='public',slug='real-store-site')
    stored = root / (artifact.key + '.atomsnap')
    original = stored.read_bytes()
    stored.write_bytes(b'broken')
    with pytest.raises(ArtifactError):
        ReleaseRepository(path).publish_verified(store, **intent)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM release_records').fetchone() == (0,)
    stored.write_bytes(original)
    first = ReleaseRepository(path).publish_verified(store, **intent)
    assert first.revision_id == adopted.revision_id and verify(path) == 13
    content = ContentRepository(path)
    binding = content.bind(owner='user', project_id='project', release_id=first.release_id)
    assert content.sharing_binding(slug=intent['slug']) == binding
    access = ContentAccessRepository(path)
    source = access.create_console_session(user_id='user', lifetime_seconds=900)
    bootstrap = access.bootstrap(binding_id=binding.id)
    handoff = access.issue_handoff(viewer_id='user', source_session_id=source.id,
        binding_id=binding.id, challenge=bootstrap.challenge)
    session = access.exchange(binding_id=binding.id, handoff=handoff.secret,
        browser_nonce=bootstrap.secret)
    with materialized_private_content(content, access, store, binding_id=binding.id,
            session_secret=session.secret) as view:
        assert (view.path / 'index.html').read_bytes() == b'<html>heat</html>'
        assert view.publication.artifact == artifact
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT live,generation FROM release_publications').fetchone() == (1,1)
        assert db.execute('SELECT event_kind FROM security_audit_events ORDER BY sequence').fetchall() == [
            ('release.published',), ('console.session.created',),
            ('content.handoff.issued',), ('content.session.created',)]
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
