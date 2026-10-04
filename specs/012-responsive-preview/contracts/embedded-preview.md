# Embedded preview contract

- Owner POST preview-access: existing proof/cookie/Host/Origin/intent; body revisionId and optional replaceViewId. Response url, viewId, viewUrl, expiresAt, revisionId. Validate HTTPS, same IP, different port, exact path, no credentials/query before use.
- Bootstrap /_atom/open removes fragment before same-origin exchange. Exchange returns scoped view path, revision and expiry; sets Secure HttpOnly Lax no-Domain port-specific cookie with per-view Path.
- Content /_atom/view/<64hex selector>/<path>: match selector/cookie/project/source/revision on every read. Generated _atom namespace stays reserved.
- Trusted per-view /_atom/resume checks authorized entry and reports atom.preview ready/error to exact console before navigating. Parent validates origin/window/view/message. UI status cannot become acceptance evidence.
- Root resource redirects use only exact same-origin scoped Referer; no private content before destination authentication. Missing/malformed/foreign hint denies. No source rewrite or latest-version fallback.
- CSP permits only canonical console framing. Public profile unchanged. No credentialed CORS, generated console tokens, worker or top-navigation authority.
- Quotas/expiry bounded. Refresh reuses view; replacement affects only caller-named owned source-session view. Popup gets independent grant.
- 400 malformed;403 wrong Origin/intent;404 denied/revoked;429 capacity;503 unavailable. UI exits loading within20s and offers retry. Never display/log secrets.
