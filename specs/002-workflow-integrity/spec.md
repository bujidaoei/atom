# Specification: Workflow integrity
Created: 2026-09-30 | Status: implemented and locally verified; production verification pending

## User Scenarios & Testing
### US1 Trust project actions (P1)
Switch rapidly between projects, open two tabs, and retry a lost startup response. Each command runs once; messages, errors and late responses stay with their project. A completed project never shows a different project's startup error.
### US2 Reliable file inspection (P1)
Read a long file and follow its continuation hint; search with the same in-workspace path used to write it. Both succeed. External paths and traversal remain rejected.
### US3 Recover individual race candidates (P1)
Choose an explicit 3, 6 or 10 minute per-candidate budget. After a candidate times out, continue that candidate from its existing files without regenerating successful candidates. Successful candidates remain adoptable after the race finishes. Never label partial previews complete.

## Requirements
- FR001 Isolate project page state, in-flight responses and event subscriptions by project; ignore stale responses.
- FR002 Persist command receipts for plan/approve/revise/race/retry. Same key and request replays the same receipt; changed request with reused key is rejected. Startup status is persisted before acknowledgment.
- FR003 Initial automatic planning is a once-only command across page reloads, not repeated when clarification returns to draft.
- FR004 Read parameters and continuation hints agree; workspace absolute and relative paths resolve consistently, without permitting escapes.
- FR005 Race budgets are explicit and bounded; retry preserves candidate files, model and contract. Failed candidate details and next actions remain visible.
- FR006 Preserve existing data and historical evidence. Test real UI navigation and real tool invocations, plus controlled faults, before deployment.
- FR007 Application startup must not depend on third-party font availability. Serve existing font faces with application assets and verify a real browser can load without external font requests.

## Success Criteria
No duplicate runs in simultaneous startup/lost-response tests; no cross-project state in delayed-response/navigation tests; long-read continuation and confined absolute search pass; candidate retry changes only selected candidate and terminal status survives reload. Real minesweeper/match-three flows are exercised and failures reported honestly.

## Assumptions
Single API worker retained. Model latency and generated app correctness remain variable; a time budget is not a completion guarantee. Existing users' apps and contracts are inspected read-only. Existing visual language is preserved.
