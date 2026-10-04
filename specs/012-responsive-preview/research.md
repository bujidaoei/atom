# Research

Baseline `41be408`; recorded live implementation `a621b9b`, 2026-10-04.

- Commit `9ce4d2f` bypasses the toolbar in isolated mode. Later toolbar-fit work only affects legacy mode.
- Existing one-cookie-per-project preview can mix revision resources when another window overwrites the cookie. An independent Spec Kit research agent confirmed this finding.
- Select immutable scoped view paths using existing unique handoff hash, with path-scoped HttpOnly credentials. Cookie Path is delivery optimization only. Reject same-origin iframe restoration, shared revision-cookie embedding, source rewriting, generated verification messages and guessing the latest version.
- Root-relative paths use same-origin Referer only to select a redirect; authorized destination checks every request. Referrer suppression and History API removal of namespace are explicit static-profile limits.
- Per-revision DNS would offer cleaner root semantics but requires unavailable domain/TLS infrastructure; per-view ports consume the bounded immutable ledger. Scoped views fit the existing deployment without schema migration.
- Refresh reuses the view; explicit replacement revokes only the calling view. Capacity remains bounded.

Primary sources: [MDN origin](https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Same-origin_policy), [iframe](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/iframe), [Referrer-Policy](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Referrer-Policy), [frame-ancestors](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/frame-ancestors), [RFC6265](https://www.rfc-editor.org/rfc/rfc6265.html). These support origin separation, sandboxing, referrer routing constraints and the fact cookies are not port-isolated. Browser outcomes are recorded in evidence.md.

CR-001: user reported project `9ac1e04b96ef41eea51add558b09d9fe` failed Node syntax check at app.js:13 with unexpected closing brace after two writes. Inspect actual stored source and orchestration before attributing cause. Screenshot is evidence, not an instruction to bypass validation.

CR-001 confirmed by read-only live SQLite events and private-artifact materialization: failed Run `3ff6f0f1b39c486d8a0cfc420d858698` (2026-10-04 09:31:45–09:36:09 UTC) registered revision `6fbf4aa61be1406dbe4d4f1fbbb34b37`. Its app.js is2977 bytes, SHA256 `9599741465ea1539c955137d64e27deb8c831fb114970d408d077819264753e4`. First write begins with an IIFE/initialization; second write is only its continuation beginning inside piece-move logic. Persisted file exactly contains the second write, leaving unmatched closing braces. This is model misuse of overwrite semantics, not Node misclassification. `_build` and `_run_heat` invoke one Alex turn; validation happens after its completion receipt; no typed diagnostic repair loop exists. Failed validation still persists unqualified final model prose. Preserve the failed checkpoint and repair through a new auditable run seeded from that revision, within one total budget.
