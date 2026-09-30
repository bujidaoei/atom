# Tasks: Verified sandbox snapshots

## Phase 1: Setup
- [x] T001 Specify bounded scope, research and design in specs/006-sandbox-snapshots/spec.md and plan.md.

## Phase 2: Foundation
- [x] T002 Implement validated limits, strict manifest and portable path rules in backend/app/snapshots.py (FR-001/002/003/006).

## Phase 3: US1 — Preserve verified work
Independent test: byte-exact round trip and no completed partial output.
- [x] T003 [US1] Add real receive/corruption/failure tests in backend/tests/test_snapshots.py.
- [x] T004 [US1] Implement bounded verified staging and unique completion in backend/app/snapshots.py (FR-001/004).

## Phase 4: US2 — Reject unsafe and excessive work
Independent test: Linux real filesystem links/special files, path aliases and limit boundaries.
- [x] T005 [US2] Add hostile manifests, policy limits and actual Linux filesystem tests in backend/tests/test_snapshots.py.
- [x] T006 [US2] Implement descriptor-relative export, exclusions and consistency checks in backend/app/snapshots.py (FR-002/003/005/006).

## Final phase: Acceptance and synchronization
- [x] T007 Run Windows and Linux component tests plus backend regression; record actual results/limits in specs/006-sandbox-snapshots/evidence.md (FR-007).
- [x] T008 Review code and cross-artifact scope; synchronize specs/003-enterprise-foundation/tasks.md and evidence.md. Delivery commits must include only reviewed files, leaving unrelated user edits.

## Dependencies and strategy
T001→T002; T003 precedes T004, T005 precedes T006, T004/T006→T007→T008. US1 and US2 share one module and remain sequential; independent source research can run alongside specification. Complete the component before broker integration. No production call-site or isolated runtime acceptance is implied by these tasks.
