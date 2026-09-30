# Plan: Workflow integrity
Branch: codex/002-workflow-integrity | Spec: spec.md

## Technical context
Existing FastAPI/SQLite single-worker coordinator, React19, Node24/Pi adapter; additive command receipt table via existing create_all initialization. No locked Pi changes.

## Design
Command receipts scoped to owned project/key with canonical payload digest and stored response; replay before state guards. Registration persists planning/building before asynchronous execution. Frontend initial-plan uses deterministic key and transport retry reuses key. Project-keyed page plus lifecycle/request-sequence guards isolate asynchronous reads and closed streams.
Read aliases offset/limit and startLine/maxLines use one range normalizer, reject contradictory aliases; trusted Pi read hint stays compatible. Grep/glob paths resolve inside real workspace, Python retains symlink confinement.
Race API accepts bounded per-request budget; a retry creates a new run in the existing heat workspace. Historical runs remain, other heats are untouched; totals are cumulative. Explicit controls use current Atom components, no visual redesign.
Cancelled heat metrics retain actual file counts and usage. Retry elapsed display uses the latest run UTC timestamp plus accumulated time. Partial entry points may be previewed but never adopted as complete. Completed Mike/Emma stream messages use the persisted readable form instead of continuing to display raw JSON. Draft startup errors expose a same-key retry and all action banners can be dismissed.

## Constitution check
Spec/task/evidence tracking, real tests, immutable Pi and secret exclusion satisfied. Existing user edits preserved. Additive table is backward-compatible; backup and image rollback required.

## Validation
Production follow-up: an unresolved Google Fonts stylesheet blocked the inline theme script, body parsing and application mounting. Bundle pinned Fontsource IBM Plex Sans/Mono faces via Vite, preserving typography with font-display swap. Validate same-origin font requests and browser startup before redeploying after active test jobs finish.

Backend receipt/race tests; actual Pi read continuation and absolute grep; real browser delayed navigation, multi-tab startup, stale stream and action errors; build/hash checks; production minesweeper/match-three smoke. Record actual failures as well as passes.
