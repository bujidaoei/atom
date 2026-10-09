# Evidence — interaction integrity

2026-10-09: clean source workspace began at 980c38c; origin/main bc091e6 is an ancestor. Current production source 969d1cca95ff06edd83ab2d85240af2bd68bc5f0, image sha256:d2611d77bc7f5e5cb136cb2105ecd8e0e83b613b7f9d94f7e00b2e5647cb594f. Existing SSH key authorization succeeded; supplied passwords were not persisted.

Read-only production SQLite/COS source diagnosis:
- Calculator 540e8d66b9cd440c999ba0d77b114dd2; head 8660315b0b92499fa3ff96afac7f19f8; artifact 0ea8043e4b80278a4521c4b958b2849bdbec48c077fd3900ef30f49e8157666d. form submit listener plus independent keydown Enter handler.
- Todo 9e91893909264cd78fe67a157607cc2d; head 224d1577e8024c47985534852ed1291e; artifact eaaff5d807b2088b3785e4dddadce99c5d90dd124a79cfb092cc18924484243e. Submit handler adds item.
- Expense ea79e1736c0e40fa80f5488f7d3eca8d; head 1fda57d55e6f470783cc7b6cd381439f; artifact 6069a014dd648c6b1279e947469e301b96fd54b2d2c75b6ec1130f373cdc85c7. Submit handler adds record.
- Keypad calculator 89c98b825b7141dca8b2556f5d1b7787; head 6f0ca16309c1479f8d956e2cf4c60131; artifact af43dac6b543c81a3b3f0665b76d9fa9de8fb66d3a287d6e150bee77d70c2b19. Direct button click handlers.

Controlled Chromium reproduction confirms sandbox form-event blocking. Exact source capture is .logs/interaction-original-artifacts.json, ignored, no credentials. Existing logged-in Edge account cannot open colleague-owned calculator (owner-scoped project_not_found), confirming isolation; do not claim that owner UI session accepted colleague projects. Artifact replay and authenticated owner acceptance will be recorded separately.


## Implemented/local observed gates
- Test before change: test_content_forms_browser Chromium failed with valid input and click count0 instead of1. After shared CSP/iframe changes, all6 engine/context scenarios passed, including native validation, exactly-once click/Enter/requestSubmit and actual no-interception same-origin/external GET/POST transport denial.
- Focused original observer/origin/form suite17passed; subsequently expanded pinned-origin suite7passed, including shared header equality, valid form flow, same/external fetch and native form transport denied reports. Policy violations now fail checks even when CSP prevents a request before route interception.
- Actual PreviewService/ContentService/workspace TLS browser suite10passed. Added built-workspace form interaction then reran all3 engines:3passed,3unrelated deselected. A layer missing allow-forms fails the actual click assertion.
- Original COS source replay:24 old-policy observations and24 new-policy scenarios across4 artifacts/3engines/2contexts. Chromium/Firefox reproduce the3 form-button failures; WebKit's original replay submits successfully in both contexts (implementation difference, not a universally reproduced old failure). New-policy scenarios all pass arithmetic, error/clear/history/Enter, todo add/complete/delete/reload, expense add/total/delete/reload/Enter and existing direct-click keypad history/reload. Sources remain unmodified; calculator history restore fills operands and requires Calculate to show the restored result, matching its actual code.
- Frontend TypeScript/Vite build passed; frontend12 Node tests and existing real browser harness passed expected success/failure assertions. Runtime42passed,1opt-in real broker test skipped; all1905 SHA-locked Pi files verified. No new live model call has yet been observed.
- Broad non-browser/non-opt-in backend sweep is in progress in .logs/interaction-backend.txt and XML. No result claimed yet.

## Operator production-browser method
Use normal PreviewAccessRepository.issue/exchange against the original revision and an existing active owner console session; it performs ownership, head, capacity and expiry checks and records real preview audit events. No console session or business rows are invented. Ephemeral bounded preview cookies flow directly from API subprocess stdout into disposable browser stdin, never logs/files. The browser visits the actual live TLS preview and verifies exact X-Atom-Revision/CSP; an intercepted disposable console-origin harness tests embedding separately from owner UI. Existing owner Edge cannot authenticate the colleague; this method is explicit operator acceptance, not a claim of their interactive login. Test contexts keep business localStorage disposable. Revoke only issued acceptance views after evidence, preserving original owner sessions.
