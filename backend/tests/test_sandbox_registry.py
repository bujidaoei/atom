from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import threading

import pytest

from app.sandbox.grants import Grant
from app.sandbox.registry import Registry, RegistryError


@pytest.fixture
def grant():
    return Grant(jti="grant-1", org="org", project="project", run="run", attempt="first", fence=1,
                 base_revision="a" * 64, iat=1000, exp=1100)


@pytest.fixture
def registry(tmp_path):
    return Registry(tmp_path / "broker.db", clock=lambda: 1000)


def ready(registry, grant):
    attempt = registry.admit(grant)
    attempt = registry.transition(grant, attempt.version, "provisioning")
    return registry.transition(grant, attempt.version, "ready")


def test_checkpoint_confirmation_is_exact_idempotent_and_current(registry, grant):
    attempt = ready(registry, grant)
    with pytest.raises(RegistryError):
        registry.confirm_checkpoint(grant, attempt.version, 'b'*64)
    attempt = registry.transition(grant, attempt.version, 'quiescing')
    with pytest.raises(RegistryError):
        registry.transition(grant, attempt.version, 'checkpointed', revision='b'*64)
    confirmed = registry.confirm_checkpoint(grant, attempt.version, 'b'*64)
    assert confirmed.state == 'checkpointed' and confirmed.version == attempt.version + 1
    assert registry.confirm_checkpoint(grant, attempt.version, 'b'*64) == confirmed
    for version, revision in [(confirmed.version,'b'*64),(attempt.version,'c'*64),(True,'b'*64)]:
        with pytest.raises(RegistryError):
            registry.confirm_checkpoint(grant, version, revision)
    registry.revoke(grant.jti)
    with pytest.raises(RegistryError, match='grant_revoked'):
        registry.confirm_checkpoint(grant, attempt.version, 'b'*64)
    assert registry.find(confirmed.id).checkpoint_revision == 'b'*64


def test_checkpoint_ack_concurrency_restart_and_expiry(registry, grant):
    attempt = ready(registry, grant)
    attempt = registry.transition(grant, attempt.version, 'quiescing')
    expired = Registry(registry.path, clock=lambda: grant.exp)
    with pytest.raises(RegistryError, match='grant_expired'):
        expired.confirm_checkpoint(grant, attempt.version, 'b'*64)
    assert registry.find(attempt.id).state == 'quiescing'
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: registry.confirm_checkpoint(grant, attempt.version, 'b'*64), range(8)))
    assert all(item == results[0] for item in results)
    reopened = Registry(registry.path, clock=lambda: 1000)
    assert reopened.confirm_checkpoint(grant, attempt.version, 'b'*64) == results[0]
    with pytest.raises(RegistryError, match='grant_expired'):
        expired.confirm_checkpoint(grant, attempt.version, 'b'*64)


def test_checkpoint_ack_and_revoke_serialize_without_late_promotion(registry, grant):
    attempt = ready(registry, grant)
    attempt = registry.transition(grant, attempt.version, 'quiescing')
    barrier = threading.Barrier(2)
    def acknowledge():
        barrier.wait(timeout=5)
        try:
            return registry.confirm_checkpoint(grant, attempt.version, 'b'*64)
        except RegistryError as error:
            assert error.code == 'grant_revoked'
            return None
    def revoke():
        barrier.wait(timeout=5)
        registry.revoke(grant.jti)
    with ThreadPoolExecutor(max_workers=2) as pool:
        ack, cancellation = pool.submit(acknowledge), pool.submit(revoke)
        result = ack.result(timeout=10)
        cancellation.result(timeout=10)
    current = registry.find(attempt.id)
    assert current.state == 'terminating'
    assert current.checkpoint_revision == ('b'*64 if result else None)
    with pytest.raises(RegistryError, match='grant_revoked'):
        registry.confirm_checkpoint(grant, attempt.version, 'b'*64)


def test_reopen_and_idempotent_admission(registry, grant):
    first = registry.admit(grant)
    reopened = Registry(registry.path, clock=lambda: 1000)
    assert reopened.broker_id == registry.broker_id
    assert reopened.admit(grant) == first
    assert first.state == "intent"
    assert first.container_name.startswith("atom-sbox-")
    assert first.grant_fingerprint == grant.fingerprint()


def test_concurrent_real_connections_admit_once(registry, grant):
    with ThreadPoolExecutor(max_workers=8) as pool:
        attempts = list(pool.map(lambda _: registry.admit(grant), range(24)))
    assert len({attempt.id for attempt in attempts}) == 1
    assert len(registry.unterminated()) == 1


def test_conflicts_and_scope_fencing(registry, grant):
    registry.admit(grant)
    for changed in [replace(grant, project="other"), replace(grant, exp=1099), replace(grant, base_revision="b" * 64),
                    replace(grant, jti="other-grant")]:
        with pytest.raises(RegistryError, match="grant_conflict"):
            registry.admit(changed)
    with pytest.raises(RegistryError, match="stale_fence"):
        registry.admit(replace(grant, jti="other", attempt="second"))
    with pytest.raises(RegistryError, match="predecessor_unterminated"):
        registry.admit(replace(grant, jti="other", attempt="second", fence=2))


def test_revoke_before_and_after_admission_survives_restart(registry, grant):
    registry.revoke(grant.jti)
    reopened = Registry(registry.path, clock=lambda: 1000)
    with pytest.raises(RegistryError, match="grant_revoked"):
        reopened.admit(grant)
    other = replace(grant, jti="second-grant")
    active = ready(reopened, other)
    reopened.revoke(other.jti)
    with pytest.raises(RegistryError, match="grant_revoked"):
        reopened.authorize(other)
    with pytest.raises(RegistryError):
        reopened.transition(other, active.version, "quiescing")
    assert reopened.unterminated()[0].state == "terminating"


def test_state_version_checkpoint_and_termination(registry, grant):
    active = ready(registry, grant)
    assert registry.authorize(grant) == active
    with pytest.raises(RegistryError, match="version_conflict"):
        registry.transition(grant, active.version - 1, "quiescing")
    with pytest.raises(RegistryError, match="invalid_transition"):
        registry.transition(grant, active.version, "checkpointed", revision="b" * 64)
    quiescent = registry.transition(grant, active.version, "quiescing")
    with pytest.raises(RegistryError, match="invalid_revision"):
        registry.confirm_checkpoint(grant, quiescent.version, None)
    checkpoint = registry.confirm_checkpoint(grant, quiescent.version, "b" * 64)
    assert checkpoint.checkpoint_revision == "b" * 64
    with pytest.raises(RegistryError, match="invalid_transition"):
        registry.transition(grant, checkpoint.version, None)
    stopping = registry.request_termination(checkpoint.id)
    unknown = registry.record_termination(stopping.id, stopping.version, confirmed=False)
    assert unknown.state == "termination_unknown"
    later = replace(grant, jti="next", attempt="next", fence=2)
    with pytest.raises(RegistryError, match="predecessor_unterminated"):
        registry.admit(later)
    terminated = registry.record_termination(unknown.id, unknown.version, confirmed=True)
    assert terminated.state == "terminated"
    assert registry.admit(grant).id == terminated.id
    new = registry.admit(later)
    assert new.id != terminated.id
    with pytest.raises(RegistryError, match="stale_fence"):
        registry.authorize(grant)


def test_deadline_denies_access_but_admin_cleanup_remains_possible(registry, grant):
    active = ready(registry, grant)
    expired = Registry(registry.path, clock=lambda: 1100)
    with pytest.raises(RegistryError, match="grant_expired"):
        expired.admit(grant)
    with pytest.raises(RegistryError, match="grant_expired"):
        expired.authorize(grant)
    assert expired.expire_due() == 1
    pending = expired.unterminated()[0]
    assert pending.id == active.id and pending.state == "terminating"
    assert expired.record_termination(pending.id, pending.version, confirmed=True).state == "terminated"


def test_termination_intent_fences_late_completion(registry, grant):
    active = ready(registry, grant)
    stopping = registry.request_termination(active.id)
    assert registry.request_termination(active.id) == stopping
    with pytest.raises(RegistryError):
        registry.transition(grant, active.version, "quiescing")
    with pytest.raises(RegistryError, match="version_conflict"):
        registry.record_termination(active.id, active.version, confirmed=True)


def test_unknown_schema_is_not_overwritten(tmp_path):
    path = tmp_path / "other.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE unrelated(value TEXT)")
        db.execute("INSERT INTO unrelated VALUES ('preserve')")
    with pytest.raises(RegistryError, match="unsupported_schema"):
        Registry(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT value FROM unrelated").fetchone()[0] == "preserve"
        assert db.execute("PRAGMA user_version").fetchone()[0] == 0


def test_tampered_or_newer_schema_rejected(registry):
    with sqlite3.connect(registry.path) as db:
        db.execute("PRAGMA user_version=4")
    with pytest.raises(RegistryError, match="unsupported_schema"):
        Registry(registry.path)
    with sqlite3.connect(registry.path) as db:
        db.execute("PRAGMA user_version=3")
        db.execute("ALTER TABLE attempts ADD COLUMN unexpected TEXT")
    with pytest.raises(RegistryError, match="unsupported_schema"):
        Registry(registry.path)


def test_lock_timeout_is_bounded_and_redacted(registry, grant):
    limited = Registry(registry.path, clock=lambda: 1000, lock_timeout=0.05)
    db = sqlite3.connect(registry.path)
    try:
        db.execute("BEGIN IMMEDIATE")
        started = time.monotonic()
        with pytest.raises(RegistryError, match="^registry_unavailable$"):
            limited.admit(grant)
        assert time.monotonic() - started < 2
    finally:
        db.rollback()
        db.close()
    assert limited.admit(grant).state == "intent"


def test_paginated_reconciliation_and_independent_scopes(registry, grant):
    for number in range(5):
        registry.admit(replace(grant, jti=f"g-{number}", project=f"p-{number}"))
    first = registry.unterminated(limit=2)
    second = registry.unterminated(limit=2, after_id=first[-1].id)
    third = registry.unterminated(limit=2, after_id=second[-1].id)
    assert len({attempt.id for attempt in first + second + third}) == 5


def test_abrupt_process_exit_preserves_commit_and_rolls_back_uncommitted(registry, grant):
    script = """
import json, os, sqlite3, sys
from pathlib import Path
from app.sandbox.grants import Grant
from app.sandbox.registry import Registry
r = Registry(Path(sys.argv[1]), clock=lambda: 1000)
g = Grant(**json.loads(sys.stdin.read()))
a = r.admit(g)
print(a.id, flush=True)
db = sqlite3.connect(r.path)
db.execute('BEGIN IMMEDIATE')
db.execute('INSERT INTO revocations VALUES (?,?)', (g.jti, 1000))
os._exit(17)
"""
    result = subprocess.run([sys.executable, "-c", script, str(registry.path)],
                            input=json.dumps(asdict(grant)), text=True, capture_output=True,
                            cwd=Path(__file__).resolve().parents[1], timeout=10)
    assert result.returncode == 17, result.stderr
    reopened = Registry(registry.path, clock=lambda: 1000)
    assert reopened.admit(grant).id == result.stdout.strip()
    assert reopened.transition(grant, 1, "provisioning").state == "provisioning"


def test_revocation_wins_over_concurrent_admission(registry, grant):
    def admit():
        try:
            return registry.admit(grant)
        except RegistryError as error:
            assert error.code == "grant_revoked"
    with ThreadPoolExecutor(max_workers=2) as pool:
        submitted = pool.submit(admit)
        revoked = pool.submit(registry.revoke, grant.jti)
        submitted.result()
        revoked.result()
    with pytest.raises(RegistryError, match="grant_revoked"):
        registry.admit(grant)
    assert all(attempt.state == "terminating" for attempt in registry.unterminated())


@pytest.mark.parametrize("value", [0, -1, True, 1001])
def test_invalid_page_limits(registry, value):
    with pytest.raises(RegistryError, match="invalid_page_size"):
        registry.unterminated(limit=value)


def test_v1_migration_preserves_identity_ownership_and_revocations(registry, grant):
    attempt = registry.admit(grant)
    registry.revoke("revoked-before-admission")
    with sqlite3.connect(registry.path) as db:
        db.execute("DROP TABLE operations")
        db.execute("DROP TABLE orphans")
        db.execute("PRAGMA user_version=1")
        before = {table: db.execute(f"SELECT * FROM {table}").fetchall()
                  for table in ("broker_meta", "attempts", "heads", "revocations")}
    reopened = Registry(registry.path, clock=lambda: 1000)
    assert reopened.broker_id == registry.broker_id
    assert reopened.admit(grant) == attempt
    with pytest.raises(RegistryError, match="grant_revoked"):
        reopened.admit(replace(grant, jti="revoked-before-admission", run="new"))
    with sqlite3.connect(registry.path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3
        assert all(db.execute(f"SELECT * FROM {table}").fetchall() == rows for table, rows in before.items())
    assert reopened.pending_orphans() == []


def test_failed_v1_migration_rolls_back_ddl_and_version(registry):
    with sqlite3.connect(registry.path) as db:
        db.execute("DROP TABLE operations")
        db.execute("DROP TABLE orphans")
        db.execute("PRAGMA user_version=1")
        db.execute("UPDATE broker_meta SET broker_id='invalid'")
    with pytest.raises(RegistryError, match="invalid_registry_identity"):
        Registry(registry.path)
    with sqlite3.connect(registry.path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert db.execute("SELECT name FROM sqlite_master WHERE name='orphans'").fetchone() is None


def test_orphan_observation_is_durable_versioned_and_not_an_attempt(registry):
    observed = registry.observe_orphan("a" * 64, "b" * 32)
    assert registry.observe_orphan(observed.id, observed.attempt_id) == observed
    reopened = Registry(registry.path, clock=lambda: 1000)
    assert reopened.pending_orphans() == [observed]
    assert reopened.find(observed.attempt_id) is None
    with pytest.raises(RegistryError, match="orphan_identity_conflict"):
        reopened.observe_orphan(observed.id, "c" * 32)
    unknown = reopened.record_orphan_termination(observed.id, observed.version, confirmed=False)
    assert unknown.state == "termination_unknown"
    with pytest.raises(RegistryError, match="version_conflict"):
        reopened.record_orphan_termination(observed.id, observed.version, confirmed=True)
    done = reopened.record_orphan_termination(unknown.id, unknown.version, confirmed=True)
    assert done.state == "terminated"
    assert reopened.pending_orphans() == []
    with pytest.raises(RegistryError, match="orphan_identity_conflict"):
        reopened.observe_orphan(done.id, done.attempt_id)
