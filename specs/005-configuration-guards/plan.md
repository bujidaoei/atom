# Plan: configuration guards
Status: bounded implementation ready; parent enterprise release remains gated.

Use Pydantic validation in backend/app/config.py with hidden inputs in diagnostics; validate before creating storage directories. Add runtime/src/config.ts for environment parsing, safe diagnostic errors and token comparison, consumed by server.ts before listen. Authenticate health and every service route. RuntimeClient always supplies its required token, including health. No Pi or schema changes.

Configuration fields remain centralized and environment-driven. Production mode in docker-compose.yml is explicit. Generate independent keys using OS cryptographic randomness; .env.example contains blank values and instructions, never usable defaults. Update server setup to require HTTPS/cookie configuration and preserve existing secret-bearing env instead of overwriting it. Do not run production setup during this increment.

Testing: backend config matrix plus actual subprocess import failure, actual loopback runtime HTTP tests and subprocess startup exit, backend health transport test, full regressions, frontend build unchanged unless affected, Pi verifier. Fixtures supply isolated synthetic valid credentials. Node subprocesses have bounded readiness, request and shutdown deadlines and cleanup. No live provider spend necessary for this boundary.

Review refinement: API /api/health must return 503/ok=false when runtime authentication or transport fails, so existing container healthcheck observes this dependency failure. This is runtime readiness only; richer DB/model/queue health remains parent scope. Enforce LF for shell scripts after the Linux parser exposed CRLF in the Windows worktree.

Constitution: scoped tests map to CG-001…006; failed checks stay open, user file preserved, no secret values logged/committed. Parent contracts remain design; this permanent shared configuration boundary proceeds independently of paid competitor research.
