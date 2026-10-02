# Functional check repair evidence

Status: local repair verified; exact-image production rollout pending. The production traceback in feature009 identifies a timezone-naive/aware comparison in `acceptance_json`; no production mutation has occurred for this stage.

- The reported TypeError was reproduced against the production behavior before the change. Four new HTTP/SQLite cases failed before normalization and passed after it; current focused selection has **8 passed** (`test_acceptance.py` plus two real Chromium browser cases).
- Actual Chromium at 1280×800 and 390×844 used the built SPA, real FastAPI/SQLite checks and generated interactive page. Save/reload returned HTTP 200, and an injected HTTP 500 was described as an unfinished check while the previous valid result remained labeled. No browser JS errors or horizontal overflow were observed.
- `npm run build` passed TypeScript and Vite. `npm run verify:pi-source` passed upstream `f07218c4d4bbc12bef056a7058c3dd49dfe41abe`, 1,905 locked files. The source changes do not include schema, publish or runtime changes.
- Exact commit, image digest, protected preflight, target owner check and rollback receipt are pending, so T006/T007 remain open.
