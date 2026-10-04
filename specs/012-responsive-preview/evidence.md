# Evidence — 2026-10-04

## Research and implementation
Clean isolated worktree from main 41be408; unrelated original workspace edits preserved. Actual failure bytes/events, hashes and parser reproduction are in research.md. No production business source was mutated during investigation. Preview protocol, three-mode UI and CR-001 repair are implemented.

## Local executed gates
- 71 selected pytest cases passed: scoped views, preview access/service/issuer, generation repair/deployment policy, artifacts, lifecycle, runtime protocol/integrity. Actual Node parses generated files; scripted runtime is fault injection, not live model acceptance.
- Generation repair: first-failure recovery, 3-turn exhaustion, disabled policy, infrastructure non-retry, cancellation during repair, shared total deadline, persisted terminal states and actual reported token sums.
- Three real TLS built-SPA browser tests passed in Chromium, Firefox and WebKit: authenticated iframe, 12 mode switches without state loss, internal widths768/390, outer widths1440/768/390, refresh, independent popup, no opener/proof leakage, blocked generated console request, HttpOnly cookie protection, revoked-session denial and user retry, HTTP503 retry. Chromium also exercised a stalled access request reaching its deadline and retrying after abort.
- Prior targeted service plus TLS preview/public isolation suite:6 passed. Frontend TypeScript/Vite build passed. Frontend node suite12 passed, including streamed false-completion retraction. Pi source verification passed: upstream f07218c4d4bbc12bef056a7058c3dd49dfe41abe,1905 locked files.
- Real distinct snapshot test interleaves two revision namespaces and checks HTML/JS/CSS/module/SVG bytes, root redirects, unauthorized selector denial and encoded traversal denial.
- Screenshots saved under ignored .logs/preview-browser-accepted; reviewed desktop and390px layouts. Screenshot animations disabled to capture settled sidebar geometry. Toolbar stays on one line; narrow labels use existing accessible icon controls.

## Debugging evidence
Initial expiry injection attempted to mutate immutable expiry fields and was rejected by the database trigger; replaced with legitimate session revocation. A stalled browser route was already handled on abort, so the test no longer aborts it twice. These fixture failures were corrected and rerun; they are not counted as successful product acceptance. Real-browser event persistence now uses its actual fixture database rather than an unrelated default database.

## Pending release gates
Exact-source Linux image tests, main synchronization, protected deployment and authenticated live provider/browser acceptance remain open. No availability SLA or full device emulation is claimed. Browser display/readiness is not functional certification.
