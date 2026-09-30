# Broker implementation evidence — 2026-09-30
Status: **in progress**. Only T001/T002 completed. No broker service, container admission, revocation registry, typed runtime adapter or production migration exists yet.

## Baseline and design
Previous turn was progress: 1d22883 fixed own runtime post-acquisition cleanup. Current worktree rechecked; preexisting user router initializer change preserved. Read SandboxClient, actual runtime lifecycle and parent isolation/execution contracts. The shell-string port cannot enforce a file-only grant; T007 explicitly requires structured operations, not command-prefix matching. All broader story acceptance remains open.

## Grant component
Implemented immutable scoped claims and fixed-algorithm JWT signing/verification, bounded token and original lifetime, strict exact schema/types, duplicate/non-finite JSON rejection, purpose and trusted-clock checks, scope assertions and canonical claim fingerprint. The key is supplied explicitly, never read from API/runtime settings or embedded in product code. Test keys are synthetic. Registry must additionally authorize revocation, state and current ownership on each operation; cryptographic validation is insufficient by itself.

Tests first failed collection because app.sandbox did not exist. After implementation, 34 initial cases passed; extended signed malformed JSON and payload-tampering cases bring grant tests to 36. Reviewed negative tests so wrong-key token uses the correct header/purpose and actually reaches signature verification. A SHA512 negative fixture initially used a short-for-SHA512 test key and emitted a warning; doubled the synthetic key for that fixture, preserving algorithm-denial test.

Final command: `backend/.venv/Scripts/python.exe -m pytest backend/tests -q --junitxml=.logs/broker-grants-tests.xml`. Exit 0, JUnit 215 cases including existing subtests, 0 failures/errors, 5 existing Linux-only skips, 21.463 seconds. New grant cases have no skips. Existing Starlette/httpx deprecation warning remains. Linux snapshot tests were not rerun because their implementation did not change; previous Linux evidence remains scoped to 006.

## Acceptance boundaries
T002 proves the codec and scope comparisons with actual signatures and negative cases. It does not prove a denied HTTP request has zero Docker effects, because no HTTP admission path exists yet. T003…T012 remain open, including durable revoke/idempotency, independent credentials, real Docker limits/termination, runtime helpers, snapshot registration/migration and fault acceptance. No locked Pi changes, paid calls, GitHub push or server deployment occurred.
