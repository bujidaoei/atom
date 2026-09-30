# Tasks: Runtime sandbox ownership
## Setup and foundation
- [x] T001 Document defect, scope and ownership design in specs/007-sandbox-lifecycle/spec.md and plan.md.
## US1 — release on every exit
- [x] T002 [US1] Reproduce actual runtime early initialization leak in runtime/src/sandbox-lifecycle.test.ts.
- [x] T003 [US1] Implement single ownership scope in runtime/packages/agent-runtime/src/sandbox-lifecycle.ts and product-agent-runtime.ts; test success, failure, disabled, failed acquisition and awaited release.
## US2 — preserve errors
- [x] T004 [US2] Test dual errors and release failure in runtime/src/sandbox-lifecycle.test.ts; preserve causes in sandbox-lifecycle.ts.
## Acceptance
- [x] T005 Run runtime regression and Pi integrity; record exact evidence in specs/007-sandbox-lifecycle/evidence.md.
- [x] T006 Review mapping FR-001/002→T002/003, FR-003→T004, FR-004/005 and SC-001/002/003→T005/006; synchronize parent specs/003-enterprise-foundation/tasks.md and evidence.md.
## Dependencies
T001→T002→T003→T004→T005→T006. Shared runtime files require sequential edits; no parallel implementation. Component completion does not close broker T027.
