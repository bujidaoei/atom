# Feature: Explicit configuration and runtime authentication
Branch: codex/005-configuration-guards | Date: 2026-09-30 | Status: implemented, scoped automated/startup/HTTP verification passed; commit reconciliation pending
Parent: 003-enterprise-foundation FR-002/003/012, SEC-06. This is one security boundary, not enterprise production certification.

## User scenarios and acceptance
US1 (P1): Operator starts API/runtime with explicit credentials. Missing, placeholder, short or whitespace-containing credentials fail before serving requests; diagnostics identify the field without including its value. Distinct signing/service credentials are required. Valid configuration continues to serve authenticated requests.
US2 (P1): Production deployment refuses insecure session cookies and invalid/cleartext remote runtime transport. The current Node runtime has no native TLS; production listener must be loopback. Container deployment explicitly selects production mode. No insecure automatic fallback.
US3 (P1): Runtime clients must authenticate all service endpoints, including health and roles. Missing/wrong bearer token returns 401; valid token works. An empty configured token must never authorize callers.

## Requirements
- CG-001: API requires explicit signing secret and runtime token (at least 32 printable nonspace ASCII characters, no known sample placeholder); different purposes use different values. Validation errors/repr omit secret values.
- CG-002: Runtime requires the same token policy in all modes and validates environment, port and bind host before listening; production binds only a literal loopback address.
- CG-003: Production API requires Secure cookies, valid absolute runtime URL without userinfo/query/fragment, and HTTPS unless runtime is literal loopback. Cookie paths and finite positive timeout/quota ranges are validated. No signing default.
- CG-004: Runtime authorization uses constant-time digest comparison; all endpoints require it. API health probe sends service authentication and reports false for rejected runtime health. Control API health returns HTTP 503/ok=false if runtime health fails, preventing container health from treating failed authentication as ready.
- CG-005: Deployment/example/development instructions describe generation, configuration and intentional startup incompatibility. No actual key is checked in. Existing deployment script must not silently emit a knowingly rejected production configuration.
- CG-006: Real subprocess startup and HTTP negative/positive tests prove fail-closed behavior; existing backend/runtime regressions and Pi verification remain separate gates.

## Success criteria and boundaries
Every invalid configuration case refuses startup; stdout/stderr do not echo tested secret values. Real Node listener returns 401 for unauthenticated health/roles/run/cancel and succeeds for valid authenticated health/roles. Backend reports unauthenticated/unreachable runtime as unavailable. Production cookie requirement validated independently. These checks do not prove CSRF, preview origin isolation, encrypted BYOK, OS isolation, HA or live model behavior; parent retains those tasks.

## Edge cases and assumptions
Unknown environment, NaN/out-of-range port, newline token, equal signing/service key, URL userinfo/fragment, remote HTTP versus loopback HTTP, deletion of required environment variables, .env and process-variable precedence. Existing installations must supply generated keys; this intentional rejection replaces unsafe defaults rather than adding a compatibility bypass. TLS termination stays in the reverse proxy; actual certificate/domain verification belongs to deployment acceptance.
