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

## Target Linux image gate
Source f27a9b2b3cd7ade3a37f77a4180d41ab4016a93a produced image sha256:142ba90e6a78f9f518d8fe5db3a5078d4d96be8d9825171554d1db5116011d39, matching atom.revision and atom.frontend_base=/atom/. The target Docker build verified all1905 Pi files and loaded the gateway bundle. A disposable container from this exact image installed only hash-locked dev test dependencies and ran66 selected tests against /app/backend code:66 passed in20.10s. Read-only test checkout caused a harmless pytest cache warning; upstream Starlette/httpx emitted a deprecation warning. The first attempted older acceptance runner lacked pytest and was rejected; it provided no acceptance evidence. Browser matrix evidence is from the built local SPA; target live browser tests remain separate.

## Spec Kit consistency review
Used speckit-analyze read-only review after prerequisite validation.14 functional requirements and5 success criteria map to19 tasks: FR001–003/SC001/T008–010; FR004–007/SC002–003/T004–010; FR008–010/SC004/T005–011; FR011–012/SC005/T001–003,T016–019; FR013–014/T012–015. No unmapped task or blocking constitution conflict. Refresh wording now explicitly means reauthorization of the existing view, with fresh grants for replacement/retry. CR-001 is User Story4. Deployment tasks stay open until performed. No other enterprise-parent backlog is implicitly completed.


## Live first deployment and CR-002
Protected f27a9b2 cutover completed and six services became healthy. Original broken project head6fbf4aa61be1406dbe4d4f1fbbb34b37 was preserved. Real authenticated `/revise` ran Alex7ab638b221844732b671d4593da505cf, completed with actual usage12394 input/4322 output and no validation error; new registered headfd9ac7b7afe34e928efda0a43ce0aae7. Real Chromium passed three-mode and independent-window checks on both original screenshot projects. Separate-window and embedded revision response headers matched.

Live fixture correction: installing the origin proof after navigating to login raced the initial authentication request, causing some fixture login timeouts. The browser now installs its ephemeral proof before navigation, and all temporary sessions are explicitly revoked. This was not a product authentication bypass. DOM innerText also varies with responsive visibility, so revision headers and DOM textContent are used for popup identity, not viewport-dependent visible text.

A separate repository review during repeated live sessions found CR-002's handoff/session lifetime and active-quota defects. Fixed and13 relevant tests passed. This requires a new source/image; T016–019 stay open until its release completes. Final requirement/task inventory is15 functional requirements,5 success criteria and20 tasks; FR015 maps toT020.
