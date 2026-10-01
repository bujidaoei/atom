"""Publication metadata after adoption must keep its binding and audit atomic."""
from contextlib import contextmanager
import sqlite3

import pytest

from app.content_repository import ContentRepository
from app.release_repository import ReleaseRepository
from app.verification_repository import VerificationError, VerificationRepository
from test_adoption_repository import Store, prepared, snapshot
from test_adoption_verification_repository import adopted
from test_revision_migrations import legacy


@pytest.fixture
def publication(adopted):
    path, adopted_receipt, verification_intent = adopted
    payload, artifact = snapshot(b'<html>heat</html>')
    assert artifact == adopted_receipt.artifact
    verification = VerificationRepository(path)
    request = verification.reserve(**verification_intent)
    verification.record_report(owner='user', request_id=request.id,
        results=[{'key': 'page', 'checkIndex': 0, 'passed': True, 'note': 'observed'}])
    intent = dict(owner='user', project_id='project', release_id='adopted-release',
        verification_id=request.id, expected_revision=adopted_receipt.revision_id,
        expected_generation=0, policy_digest='c' * 64,
        runner_version='runner-1', audience='public', slug='adopted-site')
    return path, ReleaseRepository(path), ContentRepository(path), Store(artifact.key, payload), intent


def test_adopted_artifact_publication_binding_audit_and_revocation(publication):
    path, releases, content, store, intent = publication
    first = releases.publish_verified(store, **intent)
    binding = content.sharing_binding(slug='adopted-site')
    assert binding.release_id == first.release_id
    assert content.bind(owner='user', project_id='project', release_id=first.release_id) == binding
    assert content.resolve(binding_id=binding.id).revision_id == intent['expected_revision']
    assert releases.publish_verified(store, **intent) == first
    assert store.reads == 1
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT release_id,generation,live FROM release_publications').fetchone() == (first.release_id, 1, 1)
        assert db.execute('SELECT event_kind,release_id,revision_id,publication_generation '
                          'FROM security_audit_events').fetchall() == [
                              ('release.published', first.release_id, first.revision_id, 1)]
        assert db.execute('SELECT count(*) FROM content_bindings').fetchone() == (1,)
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    stopped = releases.unpublish(owner='user', project_id='project', command_id='stop-adopted',
                                 expected_release=first.release_id, expected_generation=1)
    assert stopped.generation == 2
    with pytest.raises(VerificationError):
        content.resolve(binding_id=binding.id)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT event_kind,publication_generation FROM security_audit_events '
                          'ORDER BY sequence').fetchall() == [
                              ('release.published', 1), ('release.unpublished', 2)]


def test_invalid_scope_stale_contract_and_bytes_cannot_publish(publication):
    path, releases, _, store, intent = publication
    for change in ({'owner': 'foreign'}, {'expected_revision': 'main-root'},
                   {'verification_id': 'unknown'}):
        with pytest.raises(VerificationError):
            releases.publish_verified(store, **(intent | change))
    with sqlite3.connect(path) as db:
        db.execute("UPDATE requirements SET title='Changed contract'")
    with pytest.raises(VerificationError, match='release_stale_evidence'):
        releases.publish_verified(store, **intent)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM release_records').fetchone() == (0,)
        assert db.execute('SELECT count(*) FROM content_bindings').fetchone() == (0,)
        assert db.execute('SELECT count(*) FROM security_audit_events').fetchone() == (0,)


@pytest.mark.parametrize('operation', ['publish', 'unpublish'])
def test_late_audit_failure_rolls_back_all_release_effects(publication, monkeypatch, operation):
    path, releases, _, store, intent = publication
    if operation == 'unpublish':
        releases.publish_verified(store, **intent)
    baseline = {}
    with sqlite3.connect(path) as db:
        for table in ('release_records', 'release_publications', 'content_bindings',
                      'command_receipts', 'security_audit_events'):
            baseline[table] = db.execute('SELECT * FROM ' + table).fetchall()
    original = releases._ledger._transaction
    @contextmanager
    def deny_audit():
        with original() as db:
            db.set_authorizer(lambda action, table, *rest:
                sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_INSERT
                and table == 'security_audit_events' else sqlite3.SQLITE_OK)
            yield db
    monkeypatch.setattr(releases._ledger, '_transaction', deny_audit)
    with pytest.raises(VerificationError, match='verification_unavailable'):
        if operation == 'publish':
            releases.publish_verified(store, **intent)
        else:
            releases.unpublish(owner='user', project_id='project', command_id='stop-adopted',
                               expected_release=intent['release_id'], expected_generation=1)
    with sqlite3.connect(path) as db:
        for table, rows in baseline.items():
            assert db.execute('SELECT * FROM ' + table).fetchall() == rows


def test_corrupt_artifact_preflight_preserves_empty_release(publication):
    path, releases, _, store, intent = publication
    from app.artifacts import ArtifactError
    with pytest.raises(ArtifactError):
        releases.publish_verified(Store(store.key, b'corrupt'), **intent)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM release_records').fetchone() == (0,)
