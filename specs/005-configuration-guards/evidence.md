# Evidence: configuration guards
Status: implemented; scoped automated/startup/HTTP verification passed, commit reconciliation pending. Previous goal turn was progress (collaboration contract, Atoms public-page observations, Windows/Linux sandbox reproduction). Current entry worktree had only user's routers/__init__.py change; preserve it.

Source: backend config defaults to dev signing secret; runtime server authorized() returns true when configured token empty. Runtime health is unauthenticated and backend probe sends no header. Tests and implementation will address CG-001…006 only; no production security certification implied.

Failing baseline captured before implementation: 18/18 new backend cases failed (invalid inputs accepted, repr exposed configuration values, invalid startup proceeded). Two actual Node subprocess/HTTP tests failed: empty-token runtime continued listening beyond the 8-second rejection deadline, and unauthenticated /healthz returned 200. Child processes were stopped by test cleanup; no real provider calls.

After first implementation: 18 backend configuration cases passed in 0.20 seconds; two actual runtime tests passed in 4.43 seconds. Added real loopback backend health-header/rejection test afterward; final broader regression still required. Startup/configuration guards do not repair OS isolation, CSRF or preview origin.

## Final verification and refinement
- Review found API health still reported ok=true on runtime failure. Expanded CG-004 and changed API health to 503/ok=false when the authenticated runtime probe fails. A real loopback receiver verifies correct and incorrect credential behavior through the API health route; unreachable-runtime test updated to the deliberate new contract.
- Final backend command: `.venv/Scripts/python.exe -m pytest -q --tb=short -o addopts= --junitxml=../.logs/configuration-tests.xml`, 104 passed in 21.23 seconds, including 19 new configuration/health cases. One existing Starlette/httpx deprecation warning; short-signing-key warnings disappeared after valid synthetic fixture secrets.
- Runtime command: `node --import tsx --test src/config.test.ts src/workspace.test.ts src/run-recovery.test.ts src/recovery-integration.test.ts`, 6 passed in 5.39 seconds. Includes 8 invalid startup configurations and actual listener rejection/authorized health/roles. Pi/workspace protocol tests use synthetic provider responses, not live model acceptance.
- Frontend `npm run build`: TypeScript and Vite passed. No UI change, so no new visual-browser acceptance claimed.
- Pi verifier: 1905 files at f07218c4d4bbc12bef056a7058c3dd49dfe41abe passed. Provider leak probe rerun with required synthetic service keys: zero capture requests, NOT_OBSERVED; narrow discovery scope preserved.
- Initial Linux `bash -n` failed on Windows worktree CRLF. Converted only deploy/server-setup.sh to LF (existing .gitattributes already requires LF); rerun in network-disabled local Linux image exited 0. PowerShell parser passed. Compose parsed with .env.example and confirmed production override without printing configuration values.
- Changed-source review and whitespace check passed. Secret-bearing configuration files were not read or modified. Setup no longer accepts credential arguments or overwrites its environment file. Deployment script was not executed; no certificate/backup/rollback gate closed.

Limits: configuration validity does not establish secret entropy, encrypted BYOK, CSRF, origin/OS isolation, tenant authorization or HA. Runtime readiness is not comprehensive database/model readiness. Production remains parent T019.
