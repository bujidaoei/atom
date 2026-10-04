# Tasks — secure responsive preview and CR-001 generation repair

## Phase 1 — Specification and research
- [x] T001 Establish specification and requirements review in specs/012-responsive-preview/spec.md and checklists/requirements.md.
- [x] T002 Research current isolation, version-cookie race and design the scoped protocol in research.md, plan.md, data-model.md and contracts/embedded-preview.md.
- [x] T003 Inspect actual failed project source/events and record CR-001 cause in research.md.

## Phase 2 — Private scoped-view foundation (US2)
Independent test: two real revision snapshots remain independent under interleaved authenticated HTTP requests; invalid access serves no artifact bytes.
- [x] T004 [US2] Add scoped-view and multi-revision contract/failure tests in backend/tests/test_preview_views.py, test_preview_service_v18.py and test_preview_access_v18.py.
- [x] T005 [US2] Implement selector authorization, bounded replacement and scoped cookies/paths in backend/app/preview_access.py, preview_cookie.py, preview_paths.py and preview_view.py.
- [x] T006 [US2] Implement trusted bootstrap/resume, preview-only ancestry and authenticated serving in backend/app/preview_exchange.py, preview_service.py and routers/preview_access.py.
- [x] T007 [US2] Pass targeted repository/HTTP/security tests and record evidence.md.

## Phase 3 — Responsive embedded UI (US1/US3)
Independent test: built workspace renders real saved content, keeps state across three modes, fits narrow panels and recovers from failures.
- [x] T008 [US1] Implement persistent scaled viewport surface and accessible toolbar in frontend/src/workspace/PreviewSurface.tsx and PreviewToolbar.tsx.
- [x] T009 [US3] Implement fenced access/loading/retry/refresh/popup lifecycle in frontend/src/lib/previewAccess.ts, workspace/IsolatedPreview.tsx and PreviewTab.tsx.
- [x] T010 [US1] Pass frontend build and actual HTTPS Chromium/Firefox/WebKit embedded functional/security tests in backend/tests/test_workspace_ip_preview_browser_v18.py.
- [x] T011 [US3] Exercise missing/expired/unavailable/stale-response states and inspect actual desktop/narrow/mobile screenshots; record evidence.md.

## Phase 4 — CR-001 generation validation repair
Independent test: real invalid JavaScript triggers bounded diagnostic repair and revalidation; cancellation/deadline/infra failures cannot loop.
- [x] T012 [US4] Specify observed repair lifecycle and failure/fee invariants in contracts/generation-repair.md and plan.md.
- [x] T013 [US4] Add failing validation/recovery tests in backend/tests/test_artifacts.py and targeted orchestrator tests.
- [x] T014 [US4] Implement typed concise diagnostics and bounded shared-budget repair in backend/app/services/artifacts.py, orchestrator.py and config.py.
- [x] T015 [US4] Pass repair success/exhaustion/cancel/deadline/infrastructure and accounting tests; record evidence.md.

## Phase 5 — Integrated release
- [x] T016 Verify spec/plan/tasks/code consistency, Pi lock, frontend build and targeted Linux exact-image tests; record evidence.md.
- [x] T017 Commit/push feature and synchronize GitHub main; record exact revisions in deployment.md.
- [x] T018 Complete current-generation preflight, protected deployment and post-cutover health/data/public checks; record deployment.md.
- [x] T019 Perform live authenticated three-mode/popup and real generation repair acceptance, synchronize all completion states and final GitHub main.

## Dependencies and execution
T001–T002 precede foundation. T004 precedes T005–T007; T008–T009 depend on protocol and precede T010–T011. CR-001 research T003 is independent of preview implementation; T012 precedes T013–T015. All functional/security gates precede T016–T019. Research can run alongside independent local work; shared-file edits remain sequential. No unchecked implementation, simulated business result or unexecuted test is accepted.

## Change CR-002 — access lifecycle acceptance finding
- [x] T020 [US2/US3] Replace sessions using their own scope after handoff collection; count only live source sessions for quota. Add real repository regressions and synchronize FR-015/research/evidence. Re-run final exact-image release gate.
