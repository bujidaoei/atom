# Tasks: 可迭代契约与历史快照
## Phase 1: Setup
- [x] T001 Investigate actual approval/build/history path in specs/013-contract-refinement/research.md.
- [x] T002 Specify stories, architecture and API/data model in specs/013-contract-refinement/.
## Phase 2: Foundation
- [x] T003 Add real SQLite migration/rollback and repository tests in backend/tests/test_contract_history.py.
- [x] T004 Implement v19 immutable snapshots and compatible consumers in backend/app/migrations/contract_history_v19.py and backend/app/contract_history.py.
## Phase 3: US1 iterative refinement
- [x] T005 [US1] Test repeated refinement, failure and exact build context in backend/tests/test_contract_refinement.py.
- [x] T006 [US1] Implement atomic planning/refinement and pinned approval in backend/app/services/orchestrator.py and backend/app/routers/projects.py.
- [x] T007 [US1] Implement two actions, pending-text guard and current contract in frontend/src/workspace/ContractTab.tsx and frontend/src/pages/Workspace.tsx.
## Phase 4: US2 history
- [x] T008 [US2] Test owner isolation, CAS, replay, preview and restore in backend/tests/test_contract_history.py.
- [x] T009 [US2] Implement owner history/restore and shared presentation in backend/app/routers/projects.py and frontend/src/workspace/HistoryList.tsx.
## Phase 5: Validation and delivery
- [x] T010 Run backend/frontend/runtime regressions and record specs/013-contract-refinement/evidence.md.
- [x] T011 Run real model and desktop/mobile browser acceptance; inspect generated behavior and record specs/013-contract-refinement/evidence.md.
- [x] T012 Rehearse protected v19 candidate migration and deployment rollback in deploy/ and specs/013-contract-refinement/evidence.md.
- [x] T013 Commit, synchronize GitHub main, deploy exact revision and verify public/owner flows; update specs/013-contract-refinement/evidence.md.
- [x] T014 Correct observed planning-prompt mismatch with fresh-context verification and validate through real refinement/build/checks.
## Dependencies and strategy
T001→T002→T003→T004→T005→T006→T007; T004→T008→T009; T007+T009→T010→T012→T013 candidate cutover→T011 live checks→T013 acceptance. Real public provider/browser acceptance requires the deployed candidate; T013 stays open until T011 passes. US1 first, then history, then acceptance. Independent migration and frontend build checks may run concurrently after their inputs stabilize. No implementation/acceptance task is complete merely because code exists.

## Follow-up: console entry regression
- [ ] T015 Reproduce blank /atom, add canonical entry redirect using existing ingress validation/rollback, test /atom and /atom/ in real browsers, deploy and record evidence.
