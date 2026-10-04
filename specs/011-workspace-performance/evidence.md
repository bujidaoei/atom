# Evidence — workspace performance
## Baseline (2026-10-04)
Production source fd191e5c6ae5dc08865539f9b897473010b74943, image sha256:143491f9c43f34a52c9b32ad5209ed83d19753f927b74a3481580623bc7340a6. Three real projects, four rounds each: baseline.jsonl. Every navigation issues7–8 detail requests; normal projects ~2.94–4.05s and four-candidate project14.03–14.07s. Zero page exceptions. Probe uses a separate temporary durable owner session, strictly verifies HTTPS and revokes session in finally.
An earlier harness matched the previous heading on two clicks; its results were rejected and are not baseline. An interrupted preliminary session is bounded to600seconds; final complete baseline session revoked.
Server cProfile:2.628s for three snapshots,2.494s in7 COS subprocess reads;21 revision transactions89ms. CPU/memory do not indicate saturation. Root disk95%; unused images older6h were pruned (no containers, data or backups removed), free space3.2->7.0GiB.
## Implemented and tested
- TypeScript/Vite /atom/ build passed; frontend native tests11/11 including100-invalidation burst, first response application, abort, deadline and retry.
- Real built-SPA HTTP/SQLite/SSE browser:30 historic project updates cause1 detail read; delayed navigation remains isolated;503 read displays error and retry recovers; actual persistent title update appears; stream.resync causes bounded reconciliation; zero page exceptions. Screenshot .logs/workspace-browser.png inspected separately.
- Linux disposable resource-limited container ran catalog tests over schema matrix:50 passed (catalog ownership/read-lock/provenance and real artifacts). No production data mounted. Corruption rejected in next request; request reuse avoids repeated downloads and does not bypass ownership.
- Full RevisionRepository matrix passed locally (742 tests).
- Runtime native tests38 passed,1 explicit skip; locked Pi1905 files verified at upstream f07218c4d4bbc12bef056a7058c3dd49dfe41abe.
- Acceptance-engine Chromium harness passed expected assertions including negative checks.
## Open gates
Complete backend regression is running and has one earlier desktop functional-check browser failure; isolated desktop/mobile rerun passed2/2. Final traceback must be reviewed before acceptance. Complete Linux route/runtime integration, exact image deployment and post-deploy measurements remain pending. No production performance improvement claimed yet.

## CR-001 and CR-002 validation update
Dynamic toolbar passed actual Chromium/FastAPI browser test across 240..890px container widths at fixed viewport, forced text-metric enlargement, viewport button selection and sidebar changes; screenshots toolbar-wide.png and toolbar-compact.png inspected. The first font-change assertion altered root rem sizing but fixed-pixel text tokens did not enlarge: corrected the test to change actual span font metrics, then passed.
Runtime native regression now 41 passed, 1 explicit skip. Frontend native tests 11 passed using the repository tsx loader; an attempted strip-only Node invocation was incompatible with TypeScript parameter properties and was corrected to the repository loader.
Initial full backend run had one failure solely in loopback Uvicorn teardown (thread still alive after 15s), following successful UI assertions; desktop/mobile isolated rerun passed. Shared browser fixture now configures 3s graceful shutdown so long-lived SSE cannot make test teardown unbounded. Full final regression is running; no final gate asserted yet.
