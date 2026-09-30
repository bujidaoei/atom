# Tasks: Provider binding
- [x] T001 [US1] Add failing binding/API/transport regressions in backend/tests/test_provider_binding.py.
- [x] T002 [US1] Implement shared endpoint/credential resolver in backend/app/services/provider_connection.py; wire backend/app/routers/settings.py and backend/app/services/orchestrator.py.
- [x] T003 [US2] Remove invented catalog fallback and isolate credential caches in backend/app/services/gateway.py; add discovery regressions in backend/tests/test_provider_binding.py.
- [x] T004 [US1] Expose repair/reset/discovery status in frontend/src/pages/Settings.tsx and frontend/src/lib/types.ts; verified in T007.
- [x] T005 Run regressions, frontend build, loopback probe and Pi verification; record actual results in specs/004-provider-binding/evidence.md. This covers listed automated checks only; browser evidence is T007.
- [x] T006 Synchronize parent tasks, review exact diff and record delivery readiness in specs/004-provider-binding/evidence.md; production delivery remains parent T019.
- [x] T007 [US1] Exercise settings repair, rejected endpoint-only edit, explicit rebind and whole-default reset in a real local browser against isolated test services; evidence recorded in specs/004-provider-binding/evidence.md. Does not close live provider or delivery gates.
Order T001 → T002 → T003 → T004 implementation → T005 → T007 → T004 acceptance/T006. US1 test: managed key never at alternate endpoint, authorized custom key works. US2 test: no fabricated catalog and no suffix collision. No checkbox closes merely from implementation presence.
