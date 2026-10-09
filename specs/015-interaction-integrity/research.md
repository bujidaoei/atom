# Research — 2026-10-09

## Confirmed evidence
Actual production inventory identifies affected projects: calculator `540e8d66b9cd440c999ba0d77b114dd2`, todo `9e91893909264cd78fe67a157607cc2d`, expense `ea79e1736c0e40fa80f5488f7d3eca8d`. Private COS reads verified the saved bytes through the existing digest-verifying store. All three use a submit button and a form submit listener. Calculator also has an independent Enter handler. Original artifact keys and captured read-only source are recorded in evidence.md; source capture is ignored under .logs.

ContentService CSP and IsolatedPreview/RaceTab iframe omit allow-forms. Real Chromium experiment reproduced click counter 0 versus Enter 1 under current CSP, and click 1 versus Enter 2 with allow-forms. HTML standard submission algorithm returns before submit when sandboxed forms is set: https://html.spec.whatwg.org/multipage/form-control-infrastructure.html#concept-form-submit. MDN documents the flag: https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/sandbox.

The verifier's pinned_snapshot_origin supplies no CSP. This divergence can accept artifacts that fail at delivery. A different saved keypad calculator `89c98b825b7141dca8b2556f5d1b7787` uses direct click handlers; it is a regression case, not the source of the form-submit failure.

## Decisions
- Centralize generated execution CSP and standard response headers in dependency-light content_policy.py already shipped in verifier COPY allowlist. Services and verifier consume identical restrictions; preview changes only frame-ancestors for the configured console.
- Enable allow-forms in response and embedding sandbox, retain form-action none to forbid native transport, connect-src none, object/worker/base restrictions and origin isolation. Browser tests must verify this combination rather than assume it is safe.
- Preserve immutable user artifact bytes; fix platform delivery instead of rewriting three projects or adding per-app click bridges.
- Strengthen future contract/build guidance for all primary mutating actions with state-specific flow expectations, native validation and keyboard parity. Preserve existing contract format and deterministic isolation.

## Alternatives rejected
Removing sandbox/CSP weakens isolation. Replacing user form handlers with direct click patches loses native semantics and misses future apps. Broadening form-action enables transport. Keeping a permissive verifier hides production regressions. Changing the contract schema is unnecessary for the proved root cause.
