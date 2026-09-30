# Tasks: Reliable generation

## Setup
- [x] T001 Initialize Spec Kit and review specs/001-generation-reliability/ design.
- [x] T002 Add failing lifecycle/protocol regressions in backend/tests/test_lifecycle.py.
## US1
- [x] T003 [US1] Bounded session recovery with tests in runtime/src/run-recovery.ts.
## US2
- [x] T004 [US2] Deadlines, cancel/restart/race finalization in backend/app/services/orchestrator.py and runtime_client.py.
- [x] T005 [US2] Ordered events and activity reconciliation in backend/app/events.py and frontend/src/workspace/useProjectStream.ts.
- [x] T006 [US2] Terminal diagnostics/retry UI in frontend/src/pages/Workspace.tsx and status types.
## US3
- [x] T007 [US3] Workspace root/cancellation and real roundtrip tests in runtime/src/local-sandbox.ts and workspace-tools.ts.
- [x] T013 [US3] Limit static builder capabilities and validate actual assets/syntax in product-agent-runtime.ts, server.ts and backend/app/services/artifacts.py.
## US4
- [x] T008 [US4] Validated setup and result accounting in parsing.py, projects.py and acceptance.ts.
- [x] T009 [US4] Real browser prerequisite regressions in frontend/tests/.
## Release
- [x] T010 Full tests/build/Pi verification recorded in evidence.md.
- [x] T011 Three live model/browser scenarios recorded in evidence.md.
- [ ] T012 Commit/push, backup/deploy and production verification in deployment.md.
- [ ] T014 Production follow-up: bounded enabled-control waits, explicit final-action semantics, valid game prerequisites and mobile generation constraints; retain failed production evidence and rerun.

Dependencies: T001 -> T002 -> T003/T004/T007/T008 -> T005/T006/T009 -> T010 -> T011 -> T012. Tests can run concurrently. Source edits sequential. Check tasks only after validation; fault injection is distinct from live evidence.
