# Feature Specification: Provider connection binding
Branch: codex/004-provider-binding | Created: 2026-09-30 | Status: bounded local acceptance passed and diff reviewed; enterprise production delivery pending
Parent: ../003-enterprise-foundation/spec.md, FR-002 and SEC-01. This increment does not close enterprise isolation or deployment gates.

## User Scenarios & Testing
### US1 — Safe model connection (P1)
Users can configure a provider without disclosing a platform credential to a different address. Existing valid default or personal connections continue to work.
Independent test: real loopback receiver with synthetic secrets plus settings API and generation resolver regressions.
Acceptance: changing only the address cannot use a platform key; changing a personal address requires explicitly supplying its credential again; malformed addresses fail before network use; legacy invalid settings remain readable and repairable but cannot execute; restoring defaults resets the address and key together while preserving the selected model.
### US2 — Honest model availability (P1)
Users can distinguish real model discovery from failed discovery. An unavailable provider must not produce invented selectable models. A saved model choice remains visible without being asserted available.
Independent test: discovery errors, empty/malformed payload, and two keys with identical suffixes must not fabricate or cross-contaminate catalog results.
### Edge cases
Equivalent normalized default URLs; masked key round trips; key removal from a custom connection; server endpoint configuration change; no default key; malformed ports/userinfo/query/fragment; concurrent read of invalid persisted settings.

## Requirements
- PB-001: One shared resolver binds endpoint and credential for discovery, planning, build, revision and races; no independent server-key fallback on a custom endpoint.
- PB-002: Changing a stored personal endpoint requires an explicit unmasked credential; invalid updates make no persistent changes and no provider request.
- PB-003: Default reset clears personal endpoint and key atomically. Persisted incomplete configuration cannot execute, but settings reads expose a repairable error without network calls.
- PB-004: Strict parsed URL validation rejects ambiguous input; credential headers reject control/whitespace. Normalize only scheme/host/default port/trailing separator without conflating different base paths.
- PB-005: Discovery does not follow redirects, does not invent models, and does not share cache entries for distinct credentials with identical suffixes.
- PB-006: Settings UI explains binding/reset and visibly distinguishes invalid configuration and unavailable discovery; no full secret returned or logged.

## Success Criteria
All negative binding tests reject unsafe combinations; controlled capture never receives the synthetic managed key after custom endpoint change. Valid personal/default connections and masked-key preservation pass. Backend regression, frontend build and Pi lock checks pass independently. Enterprise SSRF/egress, encrypted storage, origins, multi-tenant policy and live release acceptance remain parent tasks.

## Assumptions
This is the first durable resolver abstraction toward ProviderConnection in the parent design. It reuses current storage without schema changes and preserves intentional administrator HTTP endpoints for existing private deployments; TLS/egress enforcement is not claimed. No real provider or customer key is required for the security proof. Paid competitor research is independent of this defect's demonstrated behavior.
