# Private content access and revocation

Status: offline v4 data structures implemented/tested; access protocol and live authentication remain unimplemented/unaccepted. Source audit on
897054d, 2026-10-01. Extends content-origin.md; prerequisites for T015–T019.

## Evidence and current gap

Primary sources retrieved 2026-10-01:

- [OWASP session management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)
  recommends server-enforced session expiration/invalidation and describes URL
  exposure risks for session identifiers.
- [OWASP one-use token guidance](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html)
  describes random, securely stored, expiring, single-use tokens. Its subject is
  password recovery; applying these properties to content handoff is our design
  inference, not an OWASP-specified content protocol.
- [OWASP CSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
  distinguishes token/origin defenses from cookie-only assumptions.
- [MDN partitioned cookies](https://developer.mozilla.org/en-US/docs/Web/Privacy/Guides/Third-party_cookies/Partitioned_cookies)
  describes cookie partitioning by top-level site. A cookie established in one
  context cannot simply be assumed available under another top-level site.

Current security.py issues a subject/iat/exp JWT without a durable session ID.
routers/auth.py logout only deletes the cookie. ContentService deliberately
ignores console credentials and denies private content. No content access tables
or browser handoff endpoints exist. Existing browser tests establish neither
private credential exchange nor logout revocation.

## Authority and scope

Private access is a distinct, read-only capability for one immutable content
binding, one viewer, one source console session and one publication generation.
It never authorizes console APIs, other bindings, a verifier, or future releases.
Initial authorization follows the current owner-only model; organization roles
require a separate explicit policy change, not invented membership.

All checks require the source console session to remain active, its user to
remain authorized, the publication to remain live with the captured generation,
and the selected release to remain in scope. Any publication generation change
invalidates old private capabilities, including unpublish followed by republish.
Public readability remains governed separately by existing publication policy.
Downloaded bytes cannot be recalled.

## Browser-bound top-level protocol

1. Open a service-owned bootstrap endpoint on the exact pinned content host.
   It generates a cryptographically random 256-bit browser nonce, sets a short
   host-only Secure HttpOnly SameSite=Lax bootstrap cookie and stores its digest,
   binding and expiry. The nonce never enters a URL or generated artifact.
   Bootstrap is not authentication and returns no private artifact.
2. Redirect only to an explicitly configured console origin with a public
   challenge derived from that nonce and the binding ID. The authenticated
   console displays the requested project/release and requires the existing
   user's access-opening action. Merely visiting a URL must not auto-issue a
   privileged handoff. Arbitrary return URLs are forbidden.
3. An authenticated, CSRF-protected console POST issues a fresh random 256-bit
   one-use handoff. Its stored digest binds viewer, live console session, content
   binding, bootstrap challenge, publication generation and absolute expiry.
   Neither cookies nor console JWTs are forwarded to the content host.
4. Navigate to a service-owned content exchange page with the short-lived handoff
   in a fragment. This remains sensitive browser-visible data; it is not claimed
   leak-proof. The page removes the fragment with history.replaceState before any
   secondary operation. It loads no generated or third-party code and exchanges
   the handoff in a bounded same-origin POST. Browser nonce stays HttpOnly.
5. In one writer transaction, verify bootstrap digest/cookie, host, handoff,
   viewer/source session, current authorization/generation and deadlines; consume
   bootstrap and handoff and create exactly one separate content session. Set a
   host-only Secure HttpOnly SameSite=Lax cookie, clear bootstrap and navigate to
   a server-selected clean path. Never return session secrets in JSON or URLs.
6. Every document/resource request checks the content session and current source
   session/authorization/generation before serving bytes. It retains the existing
   post-IO checks, no-store policy and bounded response ownership.

Copying only the handoff URL to another browser must fail without its bootstrap
cookie. This is a proposed property requiring adversarial browser tests, not a
claim that nonce binding defeats browser compromise or stolen full credentials.
Two bootstrap attempts on the same host can replace the bootstrap cookie; the
earlier attempt must fail clearly and restart, not silently weaken binding.

## Persistence and failure semantics

Plan a new explicit offline migration, preserving v1/v2/v3 definitions and backup
rehearsals. Do not treat existing JWTs as durable-session proof.

| Entity | Required persisted properties |
| --- | --- |
| Console session | random session ID, user FK, creation/absolute expiry, nullable revocation time; newly issued signed console credential contains this ID |
| Content bootstrap | nonce digest, binding FK, creation/expiry, consumed time; no raw nonce |
| Content handoff | token digest, bootstrap reference, viewer/source-session scope, binding, publication generation, creation/expiry, consumed time; no raw token |
| Content session | independent token digest, unique consumed handoff reference, viewer/source-session scope, binding/generation, creation/expiry, revocation time; no raw token |

Immutable scope and monotonic terminal transitions need database constraints.
Expiry and token lifetimes are centrally validated configuration: initial design
limits are bootstrap/handoff at most 120 seconds and content session at most 15
minutes, also capped by source console-session expiry. These are Atom defaults to
test, not values prescribed by the sources. No silent sliding renewal.

Concurrent redemption commits one winner. Failed transaction consumes nothing.
A committed exchange whose response is lost stays consumed: reissue through the
authorized flow; never store plaintext secrets to replay the old response.
Wrong-host, wrong-browser, duplicate cookies/tokens, malformed input and expired
credentials fail without serving artifacts. Invalid input must not consume a
legitimate pending handoff. Server time before issuance also fails closed.

Console logout must revoke the durable source session before reporting success;
password/security-wide revocation must invalidate all affected source sessions.
Revocation is checked by content reads, so clearing cross-site cookies is not
required for enforcement. Revocation storage failure must not report server-side
logout success. Existing console sessions must reauthenticate at the explicit
cutover; no subject-only compatibility acceptance in the new issuer.

Bound per-user/binding outstanding bootstrap/handoff counts and exchange rate,
request bytes and processing deadlines. Garbage collection is bounded, preserves
required audit records and cannot delete evidence of active sessions. Audit only
reason/opaque operation IDs: exclude raw cookies, tokens, fragments and bodies.

## HTTP and browser requirements

Reserve a service-owned endpoint namespace and reject conflicting artifact paths
at the relevant publication/profile validation boundary. Do not silently hide
an existing generated file under an authentication endpoint.

Exchange pages use an independently defined restrictive CSP (fixed script hash,
same-origin exchange only, no generated scripts, frames, external images/forms or
workers), no-store and no-referrer. They cannot inherit generated-page inline
script allowances. Reject absent/null/wrong Origin and ambiguous authority for
exchange POSTs; exact trusted-ingress configuration is required before rollout.

Top-level private access is mandatory. Embedded private access is also a required
product capability, but is a separate implementation and acceptance step: design
explicit partitioned session transport and exact console frame-ancestors policy,
then test each supported browser with third-party-cookie restrictions. Do not
reuse the top-level cookie by assumption or silently expose content publicly.
Until this gate passes, the UI must explicitly report embedded access unavailable
and offer top-level access; this does not close the embedded-access requirement.

## Required evidence before acceptance

- Migration backup/restore, constraints and process-exit recovery.
- Concurrent exchange, wrong binding/browser/session, expiry boundaries, response
  loss, collision, denied late write and exact single consumption in real SQLite.
- Revoke while materializing/sending; logout, account revocation, publish/privacy,
  unpublish/republish must prevent subsequent authorized reads. No promise of
  retracting bytes already delivered.
- Real artifact HTTP path and browser exchange, copied-link failure, forged
  challenge/Origin, reserved-path collision, fragment/history/referrer/log checks,
  generated-code attempts to read/overwrite/use authentication state.
- Browser session restoration, multi-tab races, private top-level and embedded
  contexts under supported cookie policies; no isolated fixture alone closes the
  composed path. Public TLS and deployment rollback remain separate gates.

Offline v4 now implements the four data structures, scoped relationships,
lifetime/terminal constraints and source/consumption insertion checks. Real SQLite
and Linux crash/retry evidence is recorded under T020. No issuer, exchange,
source-session authentication or per-request private authorization is enabled;
this schema evidence does not accept the protocol or production cutover.

Console-session repository methods now operate on v4, but source authentication remains external and mandatory. Call create_console_session only after real authentication; call console_session only after verifying the signed credential's user/session identity. The ID is not accepted as a bearer token. HTTP login/logout, account-wide revocation and private capability linkage remain unimplemented.

Repository implementation now supports the proposed bootstrap/handoff/session lifecycle with purpose-separated hashes and explicit scope. Raw secrets exist in returned credential objects and must be transported safely by future HTTP code; repr suppresses them but does not make arbitrary serialization/logging safe. Console authentication and Origin/CSRF enforcement are still caller prerequisites. No cookie/exchange endpoint or private artifact serving is enabled; repository evidence does not establish browser binding transport.

Signed source-session component now exists in durable_credentials.py and rejects old subject-only JWTs. It is not selected by current login routes. A valid signature is followed by persisted scope/revocation/expiry checks; storage failure is not silently converted to logout. Dedicated issuer/audience/header/version are explicit configuration. Key rotation, real password/login/cookie integration and cutover remain unaccepted.

Private materialization and dedicated Cookie parsing now exist when an access repository is explicitly supplied to ContentService. Each view revalidates the opaque session/source/generation through all three materialization checks; credential denial returns empty 404 and DB unavailability returns 503. Duplicate or malformed content cookies do not fall back to anonymous access. Sharing remains public-only. No HTTP cookie-setting, bootstrap/exchange page or live console-auth integration is implemented.

The service-owned namespace is root `/_atom`, matched case-insensitively. Its root file or any descendant conflicts with the content profile and rejects the entire manifest before extraction. Nested project directories named `_atom` remain valid. Reserved requests bypass generated content and SPA fallback; they currently return 404 until explicit service endpoints are implemented. The future trusted publication coordinator must run the same verified-manifest check before promotion; today's metadata publication transaction does not implement that gate. Serving 503 is containment, not successful publication acceptance.

Namespace publication preflight is now implemented in publish_verified and exercised by the real artifact browser fixture. The fixture explicitly uses metadata-only publication after a rejected conflicting preflight to verify the separate serving guard; this bypass is test setup, not application behavior. Console issuer/exchange endpoints and main publication route cutover remain unimplemented.
