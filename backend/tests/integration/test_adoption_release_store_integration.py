"""Linux storage-to-adoption-to-release path with a real private artifact store."""
import json
import sqlite3
import sys

import pytest

from app.adoption_repository import AdoptionRepository
from app.artifacts import ArtifactError, ArtifactStore
from app.content_repository import ContentRepository
from app.release_repository import ReleaseRepository
from app.verification_contract import capture_contract
from app.verification_repository import VerificationRepository
from test_adoption_repository import adopt, prepared
from test_revision_migrations import legacy


@pytest.mark.skipif(sys.platform != 'linux', reason='ArtifactStore requires Linux filesystem semantics')
def test_real_stored_adopted_artifact_publishes_only_after_verified_bytes(prepared, tmp_path):
    path, main, _, payload, artifact = prepared
    root = tmp_path / 'private-artifacts'
    root.mkdir(mode=0o700)
    store = ArtifactStore(root)
    assert store.put(payload) == artifact
    adopted = adopt(AdoptionRepository(path), store)
    requirement = {'key': 'page', 'title': 'Page', 'detail': '',
                   'checks': [{'type': 'exists', 'selector': '#page'}]}
    with sqlite3.connect(path) as db:
        db.execute('INSERT INTO requirements VALUES (?,?,?,?,?,?,?)',
                   ('requirement', 'project', 'page', 'Page', '',
                    json.dumps(requirement['checks']), 0))
    verification = VerificationRepository(path)
    request = verification.reserve(owner='user', workspace_id=main, request_id='verify-stored',
        expected_revision=adopted.revision_id,
        expected_contract=capture_contract([requirement]).digest,
        policy_digest='c' * 64, runner_version='runner-1', budget_seconds=60)
    verification.record_report(owner='user', request_id=request.id,
        results=[{'key': 'page', 'checkIndex': 0, 'passed': True, 'note': 'observed'}])
    releases = ReleaseRepository(path)
    intent = dict(owner='user', project_id='project', release_id='stored-release',
        verification_id=request.id, expected_revision=adopted.revision_id,
        expected_generation=0, policy_digest='c' * 64,
        runner_version='runner-1', audience='public', slug='stored-site')
    stored = root / (artifact.key + '.atomsnap')
    original = stored.read_bytes()
    stored.write_bytes(b'broken')
    with pytest.raises(ArtifactError):
        releases.publish_verified(store, **intent)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM release_publications').fetchone() == (0,)
    stored.write_bytes(original)
    receipt = releases.publish_verified(store, **intent)
    binding = ContentRepository(path).sharing_binding(slug='stored-site')
    assert receipt.revision_id == adopted.revision_id
    assert ContentRepository(path).resolve(binding_id=binding.id).artifact == artifact
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT event_kind,revision_id FROM security_audit_events').fetchall() == [
            ('release.published', adopted.revision_id)]
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
