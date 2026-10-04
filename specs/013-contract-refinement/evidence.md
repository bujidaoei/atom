# Evidence and progress
2026-10-04: Source investigation confirms approval notes do not mutate contracts. Original workspace left untouched. Isolated branch from origin/main d2c889b.
Specification/research/design complete; implementation, automated verification, live model/browser acceptance, GitHub main synchronization and deployment remain pending.


## Implementation checkpoint
Real SQLite repository tests passed (restore, immutable update, invalid document, project scoping, pagination). Nine workflow/migration tests passed (two successive scripted refinements, Emma/Bob/parse failures, cancellation, stale/replayed restore, exact approval binding, migration rollback and backup). Scripted provider is explicitly fault injection, not real model acceptance.
Frontend TypeScript/Vite build passed. Real HTTP/SQLite desktop1280 and mobile390 Chromium workflow passed with no page exceptions or horizontal overflow. Screenshot review exposed mobile conversation taking first viewport; contract tab now follows release tab collapse pattern and requires rerun.
Forty-four targeted contract/migration/deployment checks passed after correcting version-helper connection closure and updating the writer fault-test database boundary. Complete backend suite and final browser regressions running. Live model and deployment gates remain open.
Source node_modules are ignored local junctions to installed workspace dependencies; no dependency files were changed. SHA-locked runtime/pi remains untouched.
Server preflight: services healthy, disk3.5GiB free. Removed only unused Docker build cache (5.179GB), retaining every image/container/data/backup; free disk8.1GiB. No serving deployment or database mutation yet.

## Target image and migration rehearsal
Source9cde84d454bfa6ab3f64eff2d3e6f286874436f6 built as sha256:d61e51686ca0170607ca3d93821f61b233125f6d3ec6aaa1efc6d27fd66b21ec with matching atom.revision and /atom/ frontend base. Exact image passed74 targeted contract, lifecycle, generation and forward deployment tests. Test dependencies were installed from existing hash-locked uv export in a disposable container; application import was asserted under /app/backend. Only upstream deprecation/read-only pytest cache warnings.
First build used slow upstream apt and was stopped before producing an image; configurable Tencent mirrors completed the build. First rehearsal lacked PYTHONPATH and failed before importing application code; corrected networkless read-only-source run passed v18→19, verified predecessor backup and integrity/FKs, preserving hashes of all48 original business tables. It copied a consistent SQLite snapshot of current production through a read-only mount; serving database was not mutated.
Final built browser regression passed4/4 (desktop/mobile contract and publication snapshots). Inspected corrected mobile screenshot: contract actions appear in first viewport, history remains scrollable. Additional true concurrent-writer and foreign-owner tests passed; only one expected-head writer commits.
Spec Kit analyze: FR001–003→T005–007; FR004/007→T003–006; FR005/006→T003,T008–009; FR008→T009. SC001→T011; SC002→T008–009,T011; SC003→T003,T005,T008,T010; SC004→T010–013.12/12 requirements/outcomes covered,13 tasks, no unmapped or critical finding. Pending live acceptance is not implied by this review.
