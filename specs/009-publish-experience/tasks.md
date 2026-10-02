# Tasks: Publish snapshots and optional functional checks
## Phase 1 - Setup
- [x] T001 Document user scope and official research in specs/009-publish-experience/spec.md and research.md; isolate existing changes.
## Phase 2 - Foundations
- [x] T002 Record production check traceback and release architecture constraints in specs/009-publish-experience/research.md.
## Phase 3 - US1 Understandable checks
Goal: save real observations reliably and distinguish service failure. Independent test: POST and reload with generation history.
- [x] T003 [US1] Reproduce and fix UTC comparison and response semantics in backend/app/serialize.py; regress backend/tests/test_acceptance.py.
- [x] T003a [US1] Clarify action/status/error wording in frontend/src/workspace/ContractTab.tsx and frontend/src/pages/Workspace.tsx; real browser verification.
## Phase 4 - US2 Direct publication
Goal: publish exact saved content without mandatory functional acceptance. Independent test: actual public bytes with no passing check.
- [x] T004 [US2] Complete exact policy/schema/API design against existing invariants in specs/009-publish-experience/contracts/publication.md and data-model.md.
- [x] T005 [US2] Add versioned advisory/strict publication persistence and migration tests in backend/app/migrations/ and backend/tests/.
- [x] T006 [US2] Implement exact-artifact atomic publication and explicit policy in backend/app/release_repository.py and backend/app/routers/releases.py; test authorization, idempotency, stale head and failures.
- [x] T007 [US2] Integrate content delivery and configured capability in backend/app/content_repository.py, backend/app/content_service.py and backend/app/config.py; test actual isolated public serving. Target COS cutover remains T007a/T007b.
## Phase 5 - US3 Published snapshot history
Goal: plain-language current online version and retained history with preview/restore. Independent test: two versions, restore first, reload, compare draft/live bytes.
- [x] T008 [US3] Implement bounded owner history and historical preview in backend/app/release_repository.py and backend/app/routers/releases.py with regression tests.
- [x] T009 [US3] Implement atomic restore/unpublish preserving draft and history in backend/app/release_repository.py; test failures and concurrency.
- [x] T010 [US3] Redesign frontend/src/workspace/ReleaseTab.tsx and ReleaseControls.tsx around current online version, publish updates and history using existing tokens.
- [x] T011 [US3] Verify real desktop/mobile snapshot interactions in backend/tests/ and record inspected screenshots in specs/009-publish-experience/evidence.md. Target-host acceptance remains T014.
## Phase 6 - Delivery
- [ ] T012 Run applicable backend, frontend, runtime and fault gates; record exact results and exclusions in specs/009-publish-experience/evidence.md.
- [ ] T012a Design and test an IP-only publication architecture that isolates console credentials and each project's browser storage; reject port-only/path-only proposals unless the cookie and cross-project threat model is addressed.
- [ ] T013 Rehearse protected migration and rollback, configure independent ingress in deploy/, retain private backup and deploy exact GitHub revision.
- [ ] T014 Perform real owner/public production acceptance and synchronize specs/009-publish-experience/deployment.md and tasks.md; leave any failed gate open.

## Dependencies and execution
T001-T002 precede all edits. T003 can progress while T004 is researched; T005-T007 depend on T004. T008-T010 depend on publication policy; T011 follows UI/API. T012-T014 follow implementation. Independent publication/migration tests may run concurrently; edits to shared repositories remain sequential. MVP is US1, but goal completion requires all requested publication and deployment outcomes.

## COS integration tasks
- [x] T007a [US2] Add validated COS configuration, bounded storage adapter and real round-trip/failure coverage in backend/app/config.py, backend/app/artifacts.py and backend/tests/; add secret-free .env.example.
- [ ] T007b [US2] Verify existing artifact import to COS and deployment configuration without making the shared bucket public; record specs/009-publish-experience/deployment.md evidence.
