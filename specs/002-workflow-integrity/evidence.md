# Verification evidence — workflow integrity

## Root cause evidence
Production match-three project f081c066edea46f3b259c8e0c6b52475: planning done, active_run_id null; two candidates done and two timed out. Persistent conflict banner was not a live backend lock. Minesweeper fc57e88ebada4666a237d811b824771f tool log: read_file returned `Use offset=235 to continue`, then rejected offset as an additional property. Absolute-path grep rejected an actual in-workspace app.js. These observations are recorded from read-only production inspection.

## Executed regressions
- Backend pytest: 59 passed, including simultaneous same-key plan/approve/revise requests, replay after cancel, changed-payload rejection, race/retry receipts, candidate isolation, budget propagation and cancelled file accounting.
- Runtime: 4 passed; actual Pi long-file continuation via offset/limit, startLine/maxLines compatibility, confined absolute grep/glob, conflicting aliases and escapes, Windows child cancellation, truncation recovery.
- Real Chromium with controlled API/EventSource faults: cross-project late GET isolation, stale same-project snapshot rejection, closed-stream events ignored, lost POST response uses same key. No page errors. This is fault injection, not live model acceptance.
- Frontend reducer/prerequisite suite passed; TypeScript/Vite build passed. SHA-locked Pi verified (1905 files).

## Live workflow progress
First actual model/browser run found a newly introduced retry callback switched to preview before adoption. Fixed by separating change notification from adoption navigation. This run is not counted as passing.

Full rerun passed: both projects reached ready; duplicate real browser tabs produced one planning run; 360-second race was cancelled after real files appeared; reload preserved cancellation; continuing one candidate retained its files and model, left the sibling unchanged and allowed adoption. See evidence/local-workflow.json. No generated application files or contracts were preseeded.

Actual Chromium contract checks: minesweeper 9/9, match-three initially 8/9 (missing non-adjacent selection feedback). A real AI revise request corrected the files; subsequent checks were 9/9 for both, with no page errors or mobile overflow. See before/after JSON and mobile screenshots. That revise request reached its 180-second deadline and ended timed_out, not done; its retained files passing browser checks does not reclassify the run as successful. This demonstrates the distinction between generated-content quality and workflow completion; no general model quality guarantee is claimed.

## Production verification
Production startup follow-up found two 30-second navigation timeouts. Independent browser tracing isolated the only pending resource as fonts.googleapis.com; the body/root had not parsed. Replaced render-blocking third-party stylesheet with pinned Fontsource 5.3.0 packages for the same font faces, bundled by Vite with swap display and license files. Local TypeScript/build and deployed actual UI fault regression passed with Google font requests deliberately held forever (zero such requests). Cold browser observation: 2.778s to DOMContentLoaded, HTTP 200, no external font requests.

Final deployed revision: 8e1ea6c6ac4fea229630b5c7dbcb647b24c43588. API/runtime health and Linux 4/4 runtime tests passed. Live isolated-account production workflow passed: duplicate tab planning produced one Mike run; minesweeper built; match-three race selected a 360s budget, cancelled with retained files, reloaded, continued only qwen and adopted it. Deepseek sibling remained unchanged. Both projects reached ready; no stale conflict banner. A test-client ECONNRESET was recorded; safe GET retry and resuming the same saved projects avoided duplicate work.

Production generated applications: first browser run passed minesweeper 10/10 and match-three 11/11 contract checks, but extra mobile QA found match-three 400px content in a 390px viewport. A real revise request corrected responsive CSS and reached ready in 38.47s. Final browser run passed all 21 contract checks with zero page errors and no mobile overflow for either app. Before/after evidence and screenshots are retained. No generated files or test expectations were manually substituted. These are sampled application contract checks, not a guarantee that every possible generated game behavior is correct.

## Limits

Single API worker. No server-side browser certification introduced. Real generated application quality and chosen model latency are measured separately; partial preview is never counted complete. Existing test-secret and Starlette deprecation warnings remain confined to test environment.
