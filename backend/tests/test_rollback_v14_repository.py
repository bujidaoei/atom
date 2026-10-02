"""Internal v14 rollback creates a new, provenance-bound verified release."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.migrations import migrate
from app.artifacts import ArtifactError, ArtifactStore
from app.release_repository import ReleaseRepository
from app.verifier_authority import VerifierAuthority
from app.verification_repository import VerificationError, VerificationRepository
from test_adoption_repository import Store, snapshot
from test_adoption_repository import prepared
from test_adoption_verification_repository import adopted
from test_revision_migrations import legacy
from test_v13_content_consumers import published
from test_verifier_authority import authorized, _register


@pytest.fixture
def historical(published, tmp_path):
    path, store, intent, source = published
    displaced = ReleaseRepository(path).publish_verified(store, **(intent | {
        'release_id': 'displaced-release', 'expected_generation': 1}))
    migrate(path, tmp_path / 'before-v14.db', target_version=14)
    return path, store, intent, source, displaced


def _rollback_intent(intent, source, displaced):
    return dict(owner='user', project_id='project', command_id='c' * 32,
                release_id='b' * 32, source_release_id=source.release_id,
                expected_release=displaced.release_id, expected_generation=2,
                expected_revision=intent['expected_revision'],
                policy_digest=intent['policy_digest'],
                runner_version=intent['runner_version'])


def test_v14_rollback_records_source_displaced_pointer_and_replay(historical):
    path, store, intent, source, displaced = historical
    repository = ReleaseRepository(path)
    args = _rollback_intent(intent, source, displaced)
    receipt = repository.rollback_verified(store, **args)
    assert (receipt.release_id, receipt.source_release_id,
            receipt.displaced_release_id, receipt.generation, receipt.slug) == (
                'b' * 32, source.release_id, displaced.release_id, 3, intent['slug'])
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT release_id,generation,live FROM release_publications').fetchone() == (
            receipt.release_id, 3, 1)
        assert db.execute('SELECT source_release_id,displaced_release_id,command_id '
                          'FROM release_rollback_sources').fetchone() == (
            source.release_id, displaced.release_id, 'c' * 32)
        assert db.execute("SELECT count(*) FROM security_audit_events WHERE event_kind='release.published' "
                          'AND release_id=?', (receipt.release_id,)).fetchone() == (1,)
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    reads = store.reads
    assert repository.rollback_verified(store, **args) == receipt
    assert store.reads == reads
    assert repository.current(owner='user', project_id='project').release_id == receipt.release_id
    with pytest.raises(VerificationError, match='release_conflict'):
        repository.rollback_verified(store, **(args | {'expected_generation': 3}))


def test_v14_rollback_denies_stale_policy_head_owner_and_bytes(historical):
    path, store, intent, source, displaced = historical
    repository = ReleaseRepository(path)
    args = _rollback_intent(intent, source, displaced)
    for change in ({'owner': 'foreign'}, {'expected_release': source.release_id},
                   {'expected_revision': 'wrong-head'},
                   {'policy_digest': 'a' * 64}):
        with pytest.raises(VerificationError):
            repository.rollback_verified(store, **(args | change))
    payload, artifact = snapshot(b'<html>wrong bytes</html>')
    assert artifact.key != store.key
    with pytest.raises(ArtifactError):
        repository.rollback_verified(Store(store.key, payload), **args)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM release_rollback_sources').fetchone() == (0,)
        assert db.execute('SELECT release_id,generation FROM release_publications').fetchone() == (
            displaced.release_id, 2)


def test_v14_rollback_denies_stale_contract_and_unverified_metadata(historical):
    path, store, intent, source, displaced = historical
    repository = ReleaseRepository(path)
    with pytest.raises(VerificationError, match='verified_release_required'):
        repository.publish(**(intent | {'release_id': 'metadata-only',
                                      'expected_generation': 2}))
    with sqlite3.connect(path) as db:
        db.execute("UPDATE requirements SET title='Changed' WHERE project_id='project'")
    with pytest.raises(VerificationError, match='release_stale_evidence'):
        repository.rollback_verified(store, **_rollback_intent(intent, source, displaced))
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM release_rollback_sources').fetchone() == (0,)


def test_v14_rollback_cannot_escalate_private_current_audience(published, tmp_path):
    path, store, intent, source = published
    displaced = ReleaseRepository(path).publish_verified(store, **(intent | {
        'release_id': 'private-displaced', 'expected_generation': 1,
        'audience': 'owner'}))
    migrate(path, tmp_path / 'before-v14.db', target_version=14)
    with pytest.raises(VerificationError, match='release_conflict'):
        ReleaseRepository(path).rollback_verified(store, **_rollback_intent(
            intent, source, displaced))
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT release_id,generation FROM release_publications').fetchone() == (
            displaced.release_id, 2)


def test_v14_rollback_late_audit_failure_preserves_displaced_pointer(historical, monkeypatch):
    path, store, intent, source, displaced = historical
    repository = ReleaseRepository(path)
    original = repository._ledger._transaction
    @contextmanager
    def deny_audit():
        with original() as db:
            db.set_authorizer(lambda action, table, *_: sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_INSERT and table == 'security_audit_events'
                else sqlite3.SQLITE_OK)
            yield db
    monkeypatch.setattr(repository._ledger, '_transaction', deny_audit)
    with pytest.raises(VerificationError, match='verification_unavailable'):
        repository.rollback_verified(store, **_rollback_intent(intent, source, displaced))
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT release_id,generation,live FROM release_publications').fetchone() == (
            displaced.release_id, 2, 1)
        assert db.execute("SELECT count(*) FROM release_records WHERE id=?", ('b' * 32,)).fetchone() == (0,)
        assert db.execute('SELECT count(*) FROM release_rollback_sources').fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM command_receipts WHERE key=?",
                          ('rollback:' + 'c' * 32,)).fetchone() == (0,)


def test_v14_rollback_competing_generation_has_single_winner(historical):
    path, store, intent, source, displaced = historical
    first = _rollback_intent(intent, source, displaced)
    second = first | {'command_id': 'd' * 32, 'release_id': 'e' * 32}
    def attempt(args):
        try:
            return ReleaseRepository(path).rollback_verified(store, **args)
        except VerificationError as error:
            return str(error)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (first, second)))
    assert len([result for result in results if not isinstance(result, str)]) == 1
    assert results.count('release_conflict') == 1
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM release_rollback_sources').fetchone() == (1,)
        assert db.execute('SELECT generation FROM release_publications').fetchone() == (3,)


def test_v14_rollback_process_death_before_and_after_commit(historical, tmp_path):
    path, store, intent, source, displaced = historical
    payload_path = tmp_path / 'source.atomsnap'
    payload_path.write_bytes(store.payload)
    args = _rollback_intent(intent, source, displaced)
    script = '''
import json,os,sys
from pathlib import Path
from app import release_repository as module
from test_adoption_repository import Store
path,payload,key,intent,stage=sys.argv[1:]
if stage=='before':
    def die(*args,**kwargs): os._exit(44)
    module.record_release_transition=die
result=module.ReleaseRepository(Path(path)).rollback_verified(
    Store(key,Path(payload).read_bytes()),**json.loads(intent))
os._exit(45)
'''
    environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1])
                       + os.pathsep + str(Path(__file__).resolve().parent))
    command = [sys.executable, '-c', script, str(path), str(payload_path),
               store.key, json.dumps(args, sort_keys=True)]
    before = subprocess.run(command + ['before'], env=environment,
                            capture_output=True, timeout=30)
    assert before.returncode == 44, before.stderr
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT release_id,generation FROM release_publications').fetchone() == (
            displaced.release_id, 2)
        assert db.execute('SELECT count(*) FROM release_rollback_sources').fetchone() == (0,)
    after = subprocess.run(command + ['after'], env=environment,
                           capture_output=True, timeout=30)
    assert after.returncode == 45, after.stderr
    receipt = ReleaseRepository(path).rollback_verified(store, **args)
    assert receipt.generation == 3
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM release_rollback_sources').fetchone() == (1,)
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_v14_keeps_trusted_verifier_registration_and_denies_plain_report(authorized, tmp_path):
    path, _receipt, request, _authority, assignment, results = authorized
    migrate(path, tmp_path / 'before-v14.db', target_version=14)
    authority = VerifierAuthority(path)
    assert VerificationRepository(path).current_scope(owner='user', project_id='project').revision_id == request.revision_id
    recorded = _register(authority, assignment, results)
    assert recorded.outcome == 'passed'
    assert VerificationRepository(path).describe(owner='user', project_id='project',
                                                 request_id=request.id).result == recorded
    with pytest.raises(VerificationError, match='verified_registration_required'):
        authority._ledger.record_report(owner='user', request_id=request.id,
                                        results=results)


def test_v14_verified_publish_and_withdraw_remain_fenced(historical):
    path, store, intent, _source, displaced = historical
    repository = ReleaseRepository(path)
    newer = repository.publish_verified(store, **(intent | {
        'release_id': 'newer-release', 'expected_generation': 2}))
    assert newer.generation == 3
    withdrawn = repository.unpublish(owner='user', project_id='project',
        command_id='withdraw-newer', expected_release=newer.release_id,
        expected_generation=3, require_verified_schema=True)
    assert withdrawn.generation == 4
    assert repository.current(owner='user', project_id='project').live is False


def test_v13_http_repository_mode_rejects_v14_before_any_release_write(historical):
    path, store, intent, source, displaced = historical
    guarded = ReleaseRepository(path, required_schema=13)
    with pytest.raises(VerificationError, match='verified_release_schema_required'):
        guarded.current(owner='user', project_id='project')
    with pytest.raises(VerificationError, match='verified_release_schema_required'):
        guarded.publish_verified(store, **(intent | {
            'release_id': 'http-must-not-publish', 'expected_generation': 2}))
    with pytest.raises(VerificationError, match='release_schema_required'):
        guarded.unpublish(owner='user', project_id='project', command_id='http-denied',
            expected_release=displaced.release_id, expected_generation=2,
            require_verified_schema=True)
    with pytest.raises(VerificationError, match='verified_rollback_schema_required'):
        guarded.rollback_verified(store, **_rollback_intent(intent, source, displaced))
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT release_id,generation,live FROM release_publications').fetchone() == (
            displaced.release_id, 2, 1)


@pytest.mark.skipif(sys.platform != 'linux', reason='ArtifactStore is Linux-only')
def test_v14_rollback_reads_real_retained_artifact_and_refuses_missing_bytes(historical, tmp_path):
    path, fixture_store, intent, source, displaced = historical
    root = tmp_path / 'retained'
    root.mkdir(mode=0o700)
    store = ArtifactStore(root)
    artifact = store.put(fixture_store.payload)
    assert artifact.key == fixture_store.key
    args = _rollback_intent(intent, source, displaced)
    (root / (artifact.key + '.atomsnap')).unlink()
    with pytest.raises(ArtifactError):
        ReleaseRepository(path).rollback_verified(store, **args)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM release_rollback_sources').fetchone() == (0,)
    assert store.put(fixture_store.payload) == artifact
    receipt = ReleaseRepository(path).rollback_verified(store, **args)
    assert receipt.source_release_id == source.release_id
