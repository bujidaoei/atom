# Implementation Plan: Generated application interaction integrity

## Summary
Repair platform sandbox form-event blocking and align acceptance with delivery, preserving immutable user artifacts and transport isolation.

## Technical Context
Existing FastAPI/Starlette static content services; dependency-light Python content_policy; real Playwright browser verifier; React/Vite iframe embedding; TypeScript generation prompts; SQLite/COS immutable revisions; protected forward image deployment, schema19 unchanged.

## Constitution Check
Spec/plan/tasks/evidence govern every gate. Preserve SHA-locked runtime/pi and unrelated user work. No credential commits, fabricated acceptance or per-project hotfixes. Backup production before traceable deployment; keep rollback and durable-write boundaries documented.

## Phase 0 research
Read-only research agent and actual COS artifact reads proved submit listeners blocked before invocation by sandbox without allow-forms. Current verifier lacks CSP. See research.md and recorded original identities.

## Phase 1 design
1. content_policy owns generated response headers/CSP with sandbox allow-scripts allow-same-origin allow-forms and form-action none. ContentService uses shared headers; PreviewService replaces only configured frame-ancestors. Verifier origin sends same base headers.
2. IsolatedPreview and RaceTab use a shared embedding sandbox constant to prevent UI policy drift. Retain origin/cookie/grant isolation.
3. Real browser regressions prove click/Enter/requestSubmit, native validation and no uncancelled same/external transport across iframe/top-level and engines. Existing verifier network-escape tests must still fail closed; observe browser security-policy violations as necessary now CSP blocks before route hooks.
4. Emma specifies a state-specific flow per primary mutating action; Alex understands local form handlers, native validation and transport denial. Existing contracts remain compatible.
5. Replay unmodified original artifact bytes under old/new delivery restrictions, verifying screenshot failures and calculator/todo/expense state changes, history/clear/dark/keypad and persistence. No user-code edits or ledger rewrites.

## Structure
backend/app/content_policy.py, content_service.py, verification_origin.py, verification_observer.py; frontend/src/workspace embedding policy and two iframe consumers; runtime/src/squad.ts; backend/tests/test_content_forms_browser.py plus focused observer/header tests; specs/015-interaction-integrity.

## Delivery
Focused and broad regression, frontend build/tests, runtime tests/Pi checks → source commit/main sync → exact target images/application and verifier tests → protected storage preflight/paired backup/cutover → production policy/real browser/immutable data checks → accepted journal and final evidence sync.

## Risks and mitigations
Allowing local form events must not enable transport (form-action none + real network observation). Verifier CSP may expose latent assumed capabilities; failed security/check tests are investigated rather than bypassed. Colleague account access is unavailable in existing Edge session; use authorized operator reads and exact production services for real original-artifact browser validation, recording any owner-session limit explicitly.
