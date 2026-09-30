# Tasks: Isolated sandbox broker
## Setup/foundation
- [x] T001 Record evidence-supported scope/design in specs/008-sandbox-broker/spec.md and plan.md.
- [x] T002 Implement strict signed grant schema/validation and negative tests in backend/app/sandbox/grants.py and backend/tests/test_sandbox_grants.py (FR-001 codec only; 36 new cases passed, HTTP zero-effects gate remains T004).
## US1 — authorized ownership
- [x] T003 [US1] Implement versioned durable registry, idempotent admission, revocation and fence checks in backend/app/sandbox/registry.py with backend/tests/test_sandbox_registry.py (FR-003 registry component; initially 17 real SQLite tests, now 20 including v1→v2 migration and orphan persistence; registry writes alone are not driver termination proof).
- [ ] T004 [US1] Implement independent broker configuration/authentication and bounded HTTP schemas in backend/app/sandbox/config.py and service.py; prove denied requests have zero driver effects (FR-001/002).
## US2 — bounded/recoverable lifecycle
- [x] T005 [US2] Implement fixed-profile Docker driver and real integration tests in backend/app/sandbox/docker_driver.py and backend/tests/integration/test_sandbox_driver.py (FR-004 driver/profile component; real CPU/PID/RAM/disk/network/deadline/ownership checks passed; service reconciliation and helper IO remain T006/T007).
- [ ] T006 [US2] Complete registry/driver reconciliation, cancellation, independent expiry and readiness in backend/app/sandbox/lifecycle.py (FR-003/005). Known-attempt coordinator, process lease, durable orphan recovery and 9 real lifecycle tests now pass. Schema v1→v2 migration preserves prior records and rolls back failures. Service scheduling and in-flight operation integration remain open; partial coordinator tests do not close this task.
## US3 — real tool and snapshot integration
- [ ] T007 [US3] Add structured file-operation contract and migrate own workspace wrappers in runtime/packages/product-contracts/src/index.ts and runtime/packages/agent-runtime/src/workspace-tools.ts; fixed broker helpers in backend/app/sandbox/file_ops.py (FR-004/007).
- [ ] T008 [US3] Implement HTTP sandbox adapter and fail-closed production selection in runtime/src/broker-sandbox.ts and config.ts; actual broker/file-tool tests in runtime/src/broker-integration.test.ts (FR-007).
- [ ] T009 [US3] Implement explicit checkpoint/registration and recovery seed lifecycle in backend/app/sandbox/checkpoints.py and runtime/packages/agent-runtime/src/product-agent-runtime.ts; exact revision/stale fence/failed promotion tests (FR-006).
- [ ] T010 [US3] Migrate API workspace/preview and persisted revision references with versioned migration in backend/app/storage.py and backend/app/migrations/; document backup/rollback in specs/008-sandbox-broker/migration.md (FR-006/007).
## Final acceptance
- [ ] T011 Run real broker/container/Pi/cancel/crash/security scenarios and relevant product regressions; record measured limits and missing gates in specs/008-sandbox-broker/evidence.md (FR-008/SC-001…004).
- [ ] T012 Review Spec Kit/code alignment and rollout readiness in specs/008-sandbox-broker/evidence.md; update parent specs/003-enterprise-foundation/tasks.md without closing enterprise release early.
## Dependencies
T001→T002→T003; T003/T004/T005→T006; T005/T007→T008; T006/T008→T009→T010→T011→T012. Shared lifecycle edits sequential. Component tests do not close user stories. Resolve concrete HTTP/registry/migration contracts within relevant tasks before their code, preserving completed invariants.
