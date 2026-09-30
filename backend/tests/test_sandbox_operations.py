from dataclasses import replace
import json
import sqlite3

import pytest

from app.sandbox.grants import Grant
from app.sandbox.registry import Registry, RegistryError


@pytest.fixture
def active(tmp_path):
    registry = Registry(tmp_path / "broker.db", clock=lambda: 1000)
    grant = Grant("g", "o", "p", "r", "a", 1, "a" * 64, 990, 1100)
    attempt = registry.admit(grant)
    attempt = registry.transition(grant, attempt.version, "provisioning")
    attempt = registry.transition(grant, attempt.version, "ready")
    return registry, grant, attempt


def test_receipt_is_durable_and_cannot_change_request(active):
    registry, grant, attempt = active
    receipt, fresh = registry.begin_operation(grant, attempt.id, "op", "b" * 64, 4096)
    assert fresh and receipt.state == "running"
    reopened = Registry(registry.path, clock=lambda: 1000)
    assert reopened.begin_operation(grant, attempt.id, "op", "b" * 64, 4096) == (receipt, False)
    with pytest.raises(RegistryError, match="operation_conflict"):
        reopened.begin_operation(grant, attempt.id, "op", "c" * 64, 4096)
    outcome = {"ok": True, "data": {"bytes_written": 3, "sha256": "c" * 64}}
    completed = reopened.complete_operation(grant, attempt.id, "op", outcome)
    assert json.loads(completed.result_json) == outcome
    assert completed.reserved_bytes == 0
    assert reopened.begin_operation(grant, attempt.id, "op", "b" * 64, 4096) == (completed, False)


def test_revocation_and_scope_deny_late_completion(active):
    registry, grant, attempt = active
    with pytest.raises(RegistryError, match="attempt_scope_mismatch"):
        registry.begin_operation(grant, "f" * 32, "op", "b" * 64, 4096)
    registry.begin_operation(grant, attempt.id, "op", "b" * 64, 4096)
    registry.revoke(grant.jti)
    with pytest.raises(RegistryError, match="grant_revoked"):
        registry.complete_operation(grant, attempt.id, "op", {"ok": True})
    assert registry.find_operation(attempt.id, "op").state == "unknown"


def test_operation_response_reservations_are_bounded(active):
    registry, grant, attempt = active
    for number in range(5):
        registry.begin_operation(grant, attempt.id, f"op-{number}", "b" * 64, 12 * 1024 * 1024)
    with pytest.raises(RegistryError, match="operation_capacity"):
        registry.begin_operation(grant, attempt.id, "overflow", "b" * 64, 12 * 1024 * 1024)
    registry.complete_operation(grant, attempt.id, "op-0", {"ok": True})
    assert registry.begin_operation(grant, attempt.id, "next", "b" * 64, 12 * 1024 * 1024)[1]


def test_v2_migration_preserves_orphan_and_attempt_state(active):
    registry, grant, attempt = active
    orphan = registry.observe_orphan("d" * 64, "e" * 32)
    with sqlite3.connect(registry.path) as db:
        db.execute("DROP TABLE operations")
        db.execute("PRAGMA user_version=2")
    reopened = Registry(registry.path, clock=lambda: 1000)
    assert reopened.broker_id == registry.broker_id and reopened.authorize(grant) == attempt
    assert reopened.pending_orphans() == [orphan]
    assert reopened.begin_operation(grant, attempt.id, "op", "b" * 64, 4096)[1]
