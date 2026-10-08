# Tasks: Artifact access recovery

- [x] T001 Diagnose actual production reads and new-run failure, correlate COS SDK result and protected configuration fingerprints; record evidence.md.
- [x] T002 Specify requirements, implementation boundaries and acceptance in spec.md/plan.md.
- [x] T003 Add credential/permission/protocol, readiness concurrency/recovery and admission regression tests. Fault-injection/real SQLite tests passed; these do not establish live COS recovery.
- [x] T004 Implement sanitized COS error mapping and user-facing storage errors; focused protocol/SDK regressions passed.
- [x] T005 Implement bounded cached readiness, health and pre-mutation admission checks; concurrent probe, recovery, HTTP admission and health tests passed.
- [x] T006 Implement explicit COS write/readback plus complete inventory deployment preflight; tests reject denied PUT/missing inventory and preserve real SQLite business rows. Successful live COS preflight remains T009.
- [x] T007 Run focused/full backend tests, frontend build and exact target-Linux tests; record results. Final non-browser/non-opt-in-integration backend sweep:3044 passed,56 skipped,86 subtests passed,exit0; frontend build and1905 locked Pi file checks passed; exact target Linux151 passed,10 subtests passed,no skips. Production browser/provider acceptance remains T010.
- [x] T008 Synchronize GitHub main and fix branch without overwriting unrelated work. Both contain application/deployment/accounting commit969d1cca95ff06edd83ab2d85240af2bd68bc5f0; protected original changes remain in named stash.
- [ ] T009 Restore valid COS credentials, verify all registered artifacts, take verified paired backup and deploy exact image through protected transaction.
- [ ] T010 Accept authenticated screenshot project opening and real new-project planning/generation in browser; record exact evidence and remaining limits.
- [x] T011 Verify pre-dispatch storage failures cannot charge credits; implement/test guarded idempotent compensation and restore the two proved incident charges after backup. Production restored2 credits; replay restored0; both original charges retained, balance80 and FK checks passed. New charge guard rollout remains part of T009.

Dependencies: T001→T002→T003→T004/T005/T006→T007. Publishing the tested source for exact server image tests requires T008 after focused regressions; the broad regression can finish concurrently. T007+T008+valid cloud credentials→T009→T010. Cloud credential repair may proceed independently. No simulated test or diagnosis closes T009/T010.
