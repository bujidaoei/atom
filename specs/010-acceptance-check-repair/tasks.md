# Tasks: Functional check repair

## Setup
- [x] T001 Record the HTTP 500 root cause and isolated release scope in specs/010-acceptance-check-repair/spec.md and plan.md.

## US1 - Save real checks
- [x] T002 [US1] Normalize UTC comparison and result time in backend/app/serialize.py with real SQLite/HTTP regression cases in backend/tests/test_acceptance.py.

## US2 - Understand the action
- [x] T003 [US2] Clarify the action, prior result and service failure in frontend/src/workspace/ContractTab.tsx and frontend/src/pages/Workspace.tsx.
- [x] T004 [US2] Run real desktop/mobile acceptance in backend/tests/test_acceptance_browser.py and record evidence.

## Delivery
- [x] T005 Run focused backend, frontend build and locked runtime checks; record exact results in specs/010-acceptance-check-repair/evidence.md.
- [ ] T006 Build the exact committed image, run protected production preflight and schema-preserving cutover with rollback in specs/010-acceptance-check-repair/evidence.md.
- [ ] T007 Confirm target owner check saves/reloads without HTTP 500 and complete deployment evidence in specs/010-acceptance-check-repair/evidence.md.

T001 precedes T002-T003; T004-T005 follow implementation; T006-T007 follow passing gates. Publication work remains in feature009.
