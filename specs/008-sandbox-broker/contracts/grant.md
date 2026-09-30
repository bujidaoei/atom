# Signed grant v1
JWT: fixed HS256 and `typ=atom-sandbox+jwt`; no arbitrary algorithm, kid, URL or critical-header negotiation. Maximum 8192 ASCII token bytes. Strict JSON rejects duplicate keys/non-finite values and unknown fields. Fixed issuer atom-control, audience atom-sandbox, subject runtime.

Claims: `jti`, `org`, `project`, `run`, `attempt` portable logical IDs (1–64 ASCII alphanumeric/underscore/hyphen, initial alphanumeric); `fence` integer 1..2^63-1; `base_revision` lowercase 64-hex; `profile=files-v1`; integer `iat`, `nbf`, `exp`, 0..2^53-1, nbf=iat, iat≤now<exp. Original exp-iat≤configured max lifetime (default 900 seconds, configuration capped at 7200). Boolean/float/string integers rejected.

Signer/verifier require dedicated 32–128 byte key. Runtime receives only token. Codec uses a trusted injected clock for tests, system UTC clock by default; request may not supply verification time. Scope assertion compares organization/project/run/attempt/fence against trusted request or registry context. Fingerprint is canonical claim SHA-256, never token or key logging.

Token validity alone grants no admission: registry must additionally check revocation/current ownership/state/deadline on every operation. No HTTP route is exposed by the grant component. All invalid-token failures return stable `invalid_grant` without raw token/claim contents; scope mismatch uses `grant_scope_mismatch`.
