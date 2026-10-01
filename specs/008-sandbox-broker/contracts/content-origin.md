# Content origin and pinned resource delivery

Status: architecture decision and acceptance contract, not implemented. Audited on d523194, 2026-10-01. Complements revision-release.md and T017/T018.

## Source evidence

deploy/nginx.conf proxies /api and /preview|p through the same server. PreviewTab.tsx enables allow-scripts and allow-same-origin. Workspace.tsx runs checks through iframe.contentDocument. These choices couple generated code to the console origin and prevent simply moving the iframe cross-origin without replacing acceptance execution. This is source analysis, not a reproduced exploit or production incident.

Browser sources retrieved 2026-10-01:

- MDN same-origin policy: origin is scheme/host/port; changing paths does not isolate origins. Cross-origin reads and writes have different rules, so CORS alone is not a mutation defense. https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Same-origin_policy
- MDN Set-Cookie: host-prefixed secure cookies require no Domain and Path=/; cookie-prefix support varies by browser. Host-only scoping is useful but is not a replacement for authorization. https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Set-Cookie
- MDN CSP sandbox: allow-same-origin retains the resource origin, while omission produces an opaque origin and changes access to storage/APIs. https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/sandbox

The following is an Atom design derived from those semantics, not a claim that headers alone implement isolation.

## Decision

Use a dedicated content site on a separate registrable domain from the console. Give each immutable serving revision/release an opaque registered host binding under that content site. Bind host to project, revision/release, purpose and audience in durable storage; do not reconstruct trust from an arbitrary Host header or a client-provided project ID. An unknown, duplicate or malformed host is rejected. DNS/TLS and proxy configuration must be explicit validated deployment inputs; there is no same-origin production fallback.

Each pinned host serves the artifact at its root. This preserves root-relative CSS/JS/image URLs and SPA paths without rewriting arbitrary generated HTML/JavaScript. Path-prefix versioning alone is insufficient: /style.css would escape that prefix. Query parameters on the entry HTML likewise do not automatically pin subrequests. Existing release IDs may not be DNS labels; allocate an independent bounded opaque route identity rather than assuming IDs are host-safe.

A stable sharing address resolves the active publication and redirects to its pinned host with no-store. Every pinned page and asset request rechecks current live status and both current/historical audience scopes. A previously public pinned host becomes inaccessible when publication is private or offline. Already downloaded bytes cannot be recalled; UI must not promise that. Retained artifacts are history, not perpetual public access.

## Authentication and control plane

- Console session cookies remain host-only, Secure and HttpOnly; production cookie-prefix migration must explicitly handle existing sessions. Never forward console cookies, bearer tokens or provider credentials to content servers.
- Private content needs a distinct audience-bound short-lived session. An authenticated console operation issues a one-use handoff bound to viewer, exact content host/revision and expiry; exchange on that exact host creates a host-only content cookie and removes the handoff from the navigation URL. Never put reusable credentials in assets, referrers or logs. Replay, wrong-host exchange and expired handoff fail.
- Top-level private navigation must work without depending on third-party cookies. Embedded private preview requires browser-tested partitioned/credential behavior; failure is an explicit access state, never public fallback.
- The content origin has no console API proxy. Control-plane mutations require explicit allowed-origin/CSRF checks in addition to authentication. Do not permit credentialed wildcard CORS or trust arbitrary forwarded-host/proto headers. Proxy trust is limited to configured ingress.
- The isolated verifier uses separate scoped credentials and an ephemeral browser context to visit a pinned artifact. It records revision/contract/environment identity through a trusted channel. Parent iframe messages and page-supplied pass claims cannot authorize release.

## Response behavior

Serve verified bytes with explicit MIME type, nosniff, no-store and no credential-bearing redirects. Admission and extraction limits apply before loading snapshots. Resolve only normalized safe paths within the verified view. Unknown asset paths return 404; HTML SPA fallback is restricted to navigation requests, not CSS/JS/image fetches. HEAD and conditional/range handling must preserve identical authorization; no 304 or shared-cache hit may bypass live checks.

Use a reviewed CSP and iframe policy for the isolated content profile. Default static profile disallows service-worker registration and uncontrolled top-level navigation/popups. Required script/form behavior and external resource destinations must be explicit policy inputs tested with actual generated artifacts. Do not silently weaken policy when an application fails. Future PWA/backend profiles require their own capability and persistence rules.

Generated content cannot access console DOM/storage. Console framing allowances belong in frame-ancestors with exact configured origins; old SAMEORIGIN headers cannot be retained blindly after isolation. Requests to other projects/releases must independently authorize. Browser storage and service-worker persistence must not transfer control across releases or tenants.

## Implementation order and gates

1. Add versioned host-binding and private handoff/session schema with collision, owner/purpose/expiry, backup/restore and concurrency tests. Preserve existing v1/v2 migration definitions.
2. Add strict content-host configuration/routing and trusted proxy boundary. Validate DNS/TLS/deployment inputs before enabling production; loopback tests do not prove public TLS.
3. Implement isolated serving with pinned root-relative assets, live audience checks, bounded views and reviewed response policy. Keep legacy production cutover disabled until the new path passes.
4. Replace console DOM acceptance with independent browser verification and explicit progress/results. Preserve honest client-reported historical records.
5. Test real browsers with malicious generated pages: parent DOM/storage access, console credentialed reads/writes, sibling project access, host spoofing, handoff replay, service-worker persistence, popup/opener behavior and external resource attempts.
6. Test a valid multi-asset app using relative and root-relative assets, navigation fallback and forms. Advance the active release between HTML and resource requests: old pinned content must remain internally consistent but still honor current unpublish/privacy. Exercise cache/back/refresh/HEAD/range and mid-read revocation.
7. Rehearse proxy/TLS, private top-level/embedded access, rollback and restore on staging before replacing live routes. No gate is satisfied by this document.

Independent content DNS/TLS is an eventual deployment input still unresolved. Schema, capability transport, browser runner and HTTP serving can be developed against explicit local test origins meanwhile. This does not authorize purchasing domains or claim deployment readiness.

Implementation progress: offline v3 now stores immutable scoped publication bindings with opaque hexadecimal route IDs and unique release identity. Migration/constraints/crash recovery are tested. Allocation/host parsing, private handoff/session and verifier environment schema are not implemented; no DNS or HTTP behavior is enabled.

Binding repository now checks owner/project/release and allocates a cryptographic random 32-hex route ID under a writer transaction. Concurrent retries reuse the unique release binding; collision denies without mutation. Resolution delegates to current publication visibility for the captured release, preserving privacy/downline rules. v2/v3 release ledgers coexist internally, but production v1 startup is unchanged. No host-header parsing, DNS or private handoff is implemented yet.

ContentHosts now validates bounded ASCII DNS suffix syntax, renders r-<binding>.<suffix> and extracts binding from exactly one actual Host header. ASCII case normalizes; optional :443 is accepted. Other ports, whitespace, trailing dots, suffix extensions, userinfo/path delimiters, invalid encoding and duplicate Host fail. Forwarded headers are ignored as authority. This does not validate public-suffix ownership, separate registrable site, TLS or trusted proxy configuration; those deployment gates remain mandatory.

Public HTTP component now reads actual verified snapshots via binding authority, supports GET/HEAD, returns empty 404/503 denials and sends no-store/nosniff/no-referrer/CSP. Extensionless browser navigations may fall back to index; missing named assets do not. Private bindings remain inaccessible even with supplied console credentials. It remains an unmounted HTTP-only component: no standalone launcher, proxy trust, TLS or private-session implementation exists. Static CSP is provisional until real browser isolation tests; network/response concurrency and cancellation gates stay open.
