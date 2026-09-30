# Tasks: configuration guards
- [x] T001 Add backend tests for CG-001/003 and safe subprocess failure in backend/tests/test_configuration.py; failing baseline captured.
- [x] T002 Add real runtime startup/auth HTTP tests for CG-002/004 in runtime/src/config.test.ts; failing baseline captured.
- [x] T003 Implement backend centralized validation and authenticated health in backend/app/config.py, services/runtime_client.py and main.py; update isolated fixtures and health tests.
- [x] T004 Implement runtime/src/config.ts and wire runtime/src/server.ts without Pi changes.
- [x] T005 Update .env.example, docker-compose.yml, scripts/dev.ps1 and deploy/server-setup.sh configuration flow; document intentional migration in docs/configuration.md. Syntax/Compose validation passed; not production execution.
- [x] T006 Execute backend/runtime regressions, production-negative subprocess checks and Pi verifier; actual results recorded in evidence.md. No production rollout or live-model claim.
- [x] T007 Reconcile spec/plan/tasks/parent evidence, inspect exact diff and commit only authorized files. Implementation committed as 050faba; no production delivery closure.
Order T001/T002 → T003/T004 → T005 → T006 → T007. Every checkbox requires its stated evidence.
