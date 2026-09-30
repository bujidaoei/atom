# Provider binding evidence
Status: implemented with automated verification, local connection browser acceptance and diff review; enterprise production delivery pending. Prior security probe observed actual credential fallback to controlled loopback receiver. No real credentials or production actions involved.
Readiness review covers all PB-001…006 in tasks T001…T004; validation T005 and status reconciliation T006 mandatory. Prior goal turn was progress: design and empirical reproduction changed next action to centralized binding implementation.

## Implementation and observed tests
- Shared provider resolver now used by settings discovery and `_gateway_for` (planning/build/revision/races). Custom endpoint without personal key refuses to resolve; endpoint changes require explicit key entry; personal credentials pin their endpoint even when initially using the managed default. Old incomplete rows are readable as unconfigured and repairable, not silently migrated to a guessed binding.
- Whole-default reset clears endpoint/key together. UI text and types reflect reset, unavailable models and repair state; local browser confirmation passed below.
- Gateway removes fictional fallback catalog, disables redirects, validates response shape and keys bounded successful-result cache by full connection digest.
- Initial regression run failed against prior code as expected. One initial failure was a test setup mistake (register already created UserSettings); fixed the fixture to modify its actual row. Do not count that failure as a product defect.
- Final backend command: `.venv/Scripts/python.exe -m pytest -q --tb=short -o addopts= --junitxml=../.logs/provider-binding-tests.xml` in backend: **85 passed**, including **26** provider cases; 20.47 seconds. Warnings: pre-existing short synthetic JWT test secret and Starlette/httpx deprecation, not production observations.
- Loopback probe after binding change: **0 capture requests**, managed test key not received, NOT_OBSERVED (narrow probe wording; assertions in API tests verify rejection/repair behavior).
- `npm run build` in frontend: TypeScript and Vite build passed.
- `node --import tsx --test src/workspace.test.ts src/run-recovery.test.ts src/recovery-integration.test.ts` in runtime: **4 passed**, including real Pi session recovery and actual workspace tools. These use controlled model protocol fixtures, not real provider business acceptance.
- `node scripts/verify-pi-source.mjs` in runtime: **1905 files verified**, upstream f07218c4d4bbc12bef056a7058c3dd49dfe41abe.

## Local browser acceptance — 2026-09-30
Actual Chrome at http://127.0.0.1:18725/app/settings, viewport 1707 × 932; actual FastAPI on loopback 18724 and temporary database. scripts/research/serve_provider_qa.py serves an explicitly synthetic catalog on 18723 with a 900-second API lifetime. This is connection UX testing, not model-generation acceptance.

- Logged in with the isolated fixture account; historical endpoint-without-key displayed a repair state and enabled default reset.
- Entered a synthetic personal key and saved: personal source and masked key appeared, with one actual HTTP catalog result.
- Changed only endpoint: save failed with a request to re-enter the provider key.
- Explicitly entered a new synthetic key: save succeeded for the changed endpoint.
- Restored default: endpoint returned to /managed, source changed to server default, reset became disabled, selected model remained unchanged.
- Screenshot inspected after async reset completed: readable controls, no clipping at tested viewport. DOM scrollWidth equaled viewport width (1707). Browser captured warning/error logs returned an empty list; this does not establish absence of all possible browser faults or mobile coverage.

## Open gates
Live provider integration and production release remain unaccepted in the enterprise parent. This change is credential binding, not complete SSRF/DNS-rebinding prevention, encrypted secret storage or isolation. Enterprise parent retains all these gates and the full original delivery objective.

## Final bounded review
Reviewed actual resolver, settings/gateway/orchestrator changes, UI/types, API contract and all provider regression cases. PB-001…006 map to T001…T004 and verification T005/T007; no runtime/pi changes. Final diff whitespace check passed with existing Windows line-ending warnings. T006 records local increment readiness only; parent T019 still forbids claiming final delivery. Preserved unrelated backend/app/routers/__init__.py modification and excluded it from the intended commit. No implementation change occurred after recorded automated/browser checks.
