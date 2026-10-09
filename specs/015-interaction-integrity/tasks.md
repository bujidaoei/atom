# Tasks: Generated application interaction integrity

## Phase 1 — investigation and specification
- [x] T001 Confirm real artifact bindings and platform/browser cause; record research.md and evidence.md.
- [x] T002 Define user outcomes, policy contract and design in spec.md, plan.md and contracts/content-execution.md.

## Phase 2 — shared execution policy (US1/US2/US3)
- [x] T003 Add real browser failing regressions in backend/tests/test_content_forms_browser.py for submit, validation, keyboard parity and blocked transport, including embedded and standalone delivery.
- [x] T004 Centralize CSP/response headers in backend/app/content_policy.py; use in content_service.py, preview_service.py and verification_origin.py.
- [x] T005 Update IsolatedPreview.tsx and RaceTab.tsx embedding policy; strengthen runtime/src/squad.ts primary-action acceptance guidance.
- [x] T006 Prove verifier flows run under delivery restrictions and preserve isolation; run service/observer/browser regressions and frontend/runtime checks.

## Phase 3 — actual project regression (US1/US3)
- [x] T007 Replay original saved COS artifact bytes with real mouse/keyboard/calculation/history/todo/expense/reload checks; capture exact digests and observed results in evidence.md.

## Phase 4 — deployment and acceptance
- [x] T008 Run broad backend regression, frontend build/tests and SHA-locked Pi verification; record skipped/unavailable gates separately.
- [x] T009 Commit and synchronize GitHub main/feature branch; build exact application/verifier images and run target Linux checks.
- [x] T010 Verify backup/storage preflight and deploy through existing protected forward transaction; record exact live identity and rollback boundary.
- [x] T011 Verify production policy, health, saved artifact identity and real browser actions; accept journal only after observed gates. Synchronize final Spec Kit evidence and progress.

Publishing focused-tested source for exact target image preparation may precede the broad sweep; production cutover still requires T008.

Dependencies: T001→T002→T003→T004/T005→T006/T007→T008→T009→T010→T011. Tests are real browser/SQLite/service evidence, not fabricated business acceptance. Research agent performed read-only investigation as prescribed by speckit-plan. All implementation is sequential to avoid shared-file conflicts.
