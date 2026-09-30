# Configuration and startup requirements

The API and Node runtime now refuse missing/short/sample credentials in every mode. Existing installations relying on dev-secret-change-me, an empty runtime token or change-me must configure new independent credentials before upgrading. This is intentional; there is no unauthenticated compatibility mode.

Generate two independent values using `openssl rand -hex 32`, or a cryptographically secure OS generator. Store one in ATOM_SECRET and the other in ATOM_RUNTIME_TOKEN in a protected untracked environment file. Never put either value in source, prompts, command arguments or tickets. API and runtime must receive the same runtime token. Rotating ATOM_SECRET invalidates old sessions; coordinate runtime-token rotation across both processes. Keep stable values across ordinary restarts.

All secrets require 32–512 printable nonspace ASCII characters and cannot contain the known sample markers. Length validation is not a proof of entropy: use generated randomness. Signing and runtime credentials must differ. Python configuration diagnostics hide input values and repr hides credential fields. This does not replace log redaction throughout the product.

For local development copy .env.example to backend/.env, fill both credentials plus provider configuration, and use ATOM_ENVIRONMENT=development. scripts/dev.ps1 validates credentials before stopping prior local processes, and passes the runtime token/environment to Node. Local HTTP may use ATOM_COOKIE_SECURE=false. Node invoked directly does not load Python's .env; supply its environment explicitly.

Docker Compose explicitly selects production and reads `${ATOM_ENV_FILE:-.env}`. Production requires ATOM_COOKIE_SECURE=true and HTTPS termination at the console reverse proxy; runtime URL must use HTTPS or a literal loopback address. The current Node sidecar has no native TLS and must bind loopback in production. Production does not imply preview isolation or CSRF protection: those enterprise gates remain open.

Runtime defaults to loopback port 8721; configure ATOM_RUNTIME_HOST/PORT explicitly when needed. It validates literal host, finite port 1–65535 and environment (development/test/production). Every runtime HTTP endpoint, including /healthz and /v1/roles, requires the bearer token. Backend health probes supply it. External probes should use the control API; do not embed runtime tokens in healthcheck command arguments.

Control API /api/health returns 503 with ok=false/runtime=false for failed runtime authentication or transport; it returns 200 only when that probe succeeds. This checks the runtime dependency, not model availability, database recovery or the full enterprise readiness contract.

The legacy Ubuntu setup helper no longer accepts an API-key argument or rewrites .env. It reads ATOM_CONFIG_FILE (default ~/.config/atom/production.env), requires mode 600 and secure cookies, and uses that file for Compose. Keep it outside the checkout. This helper still is not the enterprise backup/rollback workflow; do not use it to claim final release acceptance. Complete parent T019's backup, exact revision, recovery and live gates before production delivery.

Validation precedes storage initialization. Session lifetime is 1–90 days; model-call timeout 1–1800 seconds; run timeout 1–7200 seconds; build budget 1–1800 seconds; race count 1–16; starting credits 0–1,000,000. These are administrative validity bounds, not measured capacity or spending guarantees.
