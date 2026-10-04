# Tasks: 工作区打开性能
## Phase 1 — Specification and baseline
- [x] T001 Create validated spec and design in specs/011-workspace-performance/spec.md and plan.md.
- [x] T002 Capture real server profile and 12-click baseline in specs/011-workspace-performance/research.md and baseline.jsonl.
## Phase 2 — US1 fast opening
- [x] T003 [US1] Test and implement single-flight immediate-apply loader in frontend/src/workspace/project-loader.ts and frontend/tests/project-loader.test.ts.
- [x] T004 [US1] Add snapshot event cursor and replay invalidation filtering in backend/app/serialize.py, frontend/src/lib/types.ts and frontend/src/workspace/useProjectStream.ts.
- [x] T005 [US1] Add atomic schema-validated catalog reads and request-local manifest reuse in backend/app/revisions.py, revision_view.py, revision_http.py with repository/view regressions.
## Phase 3 — US2 recovery and navigation
- [x] T006 [US2] Integrate abort, deadline and recoverable loading/errors in frontend/src/pages/Workspace.tsx and frontend/src/lib/api.ts; fault-test cancellation, burst, trailing update and error retry.
- [x] T007 [US2] Run real browser route acceptance for replay, switching, failed reads and reconnection; record specs/011-workspace-performance/evidence.md.
## Phase 4 — US3 delivery
- [x] T012 [US2] Implement FR-007 dynamic fit measurement in frontend/src/workspace/PreviewToolbar.tsx and browser-test continuous sizing, fonts and actions in backend/tests/test_workspace_loading_browser.py.
- [ ] T013 [US2] Implement CR-002 configuration, run/model/race budget propagation, Pi overrides and deployment .env; validate delayed HTTP, cancellation and invalid settings.
- [ ] T008 [US3] Run complete backend regression, frontend tests/build, locked runtime validation and target Linux integration; record specs/011-workspace-performance/evidence.md.
- [ ] T009 [US3] Push exact reviewed source, build and deploy via protected paired-backup forward transaction; record specs/011-workspace-performance/deployment.md.
- [ ] T010 [US3] Measure same 12 live clicks and verify preview/public health and visual acceptance; record specs/011-workspace-performance/after.jsonl and evidence.md.
- [ ] T011 [US3] Synchronize GitHub main and feature branch with verified changes and final evidence in specs/011-workspace-performance/tasks.md.

Dependencies: T001-T002 -> T003/T004/T005 -> T006 -> T007/T012/T013 -> T008 -> T009 -> T010 -> T011. Independent test commands may run concurrently; implementation is sequential to avoid shared-contract drift. MVP is US1; full delivery includes all stories. Pending tests never count as accepted.

