# Executed verification — 2026-09-30

## Deterministic regression
- `cd backend && uv run pytest`: 53 passed. Covers silent deadline, early/idempotent cancel, restart, all-failed race, race cancellation, ordering/overflow, strict EOF/terminal protocol, exact acceptance coverage, actual Node syntax and missing assets.
- `cd runtime && node --import tsx --test src/*.test.ts`: 4 passed. Includes real Pi over a fault-injection HTTP provider: successful write, truncated response, durable recovery, write executed once, aggregate usage retained. This is not a live-provider quality test.
- Real filesystem/Python/Pi write/read/edit/glob/grep roundtrip in two workspaces, traversal/junction rejection pre-cancel and running background-process cancellation verified (Windows MSYS process group termination).
- `cd frontend && npm test`: 2 stream reducer tests and Chromium 145 prerequisite suite passed. Missing input, invalid selector and missing setup target fail as expected; fill/press and subsequent checks succeed, including while host preview tab is hidden.
- Frontend TypeScript and production Vite build passed.
- Pi source hash verification passed: 1,905 files at upstream f07218c4d4bbc12bef056a7058c3dd49dfe41abe.

## Live model and browser evidence
Provider: configured real gateway, deepseek-v4.1-flash. Three independent accounts/projects per round; no application files preseeded. Default build budget 180 seconds, planning time measured separately. Chromium 145, desktop 1280x800 and mobile 390x844.

| Final round | Planning | Build | Outcome | Browser contract |
|---|---:|---:|---|---:|
| Calculator | 58.27 s | 90.83 s | ready | 9/9 |
| Lottery | 64.25 s | 104.98 s | ready | 9/9 |
| Snake | 84.31 s | 80.91 s | ready | 12/12 |

All three preview requests returned 200, no pageerror events, no mobile horizontal overflow. Full check results and IDs: [browser-v3.json](evidence/browser-v3.json); measured durations: [generation-v3.json](evidence/generation-v3.json).

Earlier failures retained in evidence/: round 1 calculator contract rejected numeric keys; lottery 8/9 due animation timing; snake timed out while exploring browser tools. Round 2 calculator timed out constructing a fake DOM harness despite 10/10 functional checks. Repairs: printable keyboard keys, polling text assertions, file-only builder capabilities and platform-owned syntax gate. These unsuccessful runs were never converted into success.

## Workspace browser flow
Actual UI on http://127.0.0.1:5181: timeout notice survives reload, no stale Alex activity; continue then cancel, reload shows cancelled with no active run; continue again completes; UI contract execution persists 10/10. No page errors. Screenshots in evidence/workspace-*.png. Initial harness read results too soon and exposed hidden-tab visibility/preview-readiness issues; repaired and re-executed successfully.

## Limits
These runs verify the listed scenarios, not a statistical guarantee for all models/prompts or zero defects. Existing test environment emits Starlette test-client deprecation and short test-secret warnings. Production remains single API worker; browser acceptance is client-reported. Deployment verification is tracked separately in deployment.md.
