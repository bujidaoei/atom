# Lifecycle acceptance — 2026-09-30

Parent baseline 42419d9. Existing user routers/__init__.py edit preserved. Own runtime only; no locked Pi edits.

## Reproduction and implementation
`node --import tsx --test src/sandbox-lifecycle.test.ts` from runtime failed before implementation: real ProductAgentRuntime acquired LocalSandboxClient, injected model getter threw, expected destroy=1 but observed 0. No provider network request was made. This establishes the initialization ownership gap, not a leaked Docker container (the local adapter only registers a workspace).

Introduced one withSandbox ownership scope over every post-acquisition step. Removed three distributed destroy sites; inner session cleanup remains, outer release is awaited even when callback cleanup throws. Successful acquisition has exactly one release attempt; failed acquisition/disabled tools none. Release failure prevents success; simultaneous operation/release failure uses AggregateError with exact causes and fixed outer summary. No retry, checkpoint or publication added to destroy.

## Actual verification
- Final `node --import tsx --test src/*.test.ts` from runtime: 14 tests passed, zero failed/skipped, 4.872 seconds. Includes six ownership contract tests, actual early-initialization failure, actual initialized Pi session/event-sink failure with adapter release fault, existing authenticated HTTP/startup, real Pi recovery and real file tools.
- Recovery test now asserts two acquisitions and two releases, exactly one successful write, three synthetic provider requests and retained file bytes. This remains real Pi/tool integration against a controlled provider protocol, not a paid-model quality test.
- Release promise gate confirms result is withheld until release settles. Fault-injecting adapters verify error paths; they are not container termination evidence.
- `node scripts/verify-pi-source.mjs` from runtime: 1905 files passed at upstream f07218c4d4bbc12bef056a7058c3dd49dfe41abe.
- Reviewed whitespace-insensitive ProductAgentRuntime diff to distinguish ownership changes from callback indentation. No backend/frontend production behavior changed; their suites were not rerun for this runtime-only change.

Diagnostic history: prerequisite command initially used runtime cwd and could not locate .specify; rerun from repository root passed before implementation. Pi verifier initially used repository cwd and looked for root pi; rerun from runtime passed. Added late-failure fixture initially omitted requestTimeoutMs and correctly failed earlier at Pi settings validation; supplying 5000ms as the server does reached the intended event-sink fault. Neither failure was counted as acceptance.

## Mapping and limits
FR-001/002 and SC-001: early actual runtime reproduction plus success/failure/cancellation/disabled/acquisition/order tests. FR-003: single and dual release-error tests plus actual Pi session/event fault. FR-004/SC-002: real recovery/files and lock verifier. FR-005/SC-003: explicit scope and preserved sources.

Release attempt is not proof of OS termination. Broker must bound operations, verify kill, persist ownership and reconcile uncertain create outcomes. No Docker/grant/registry/snapshot promotion or crash-recovery acceptance. If inner session disposal replaces an earlier session operation error, this component preserves the resulting callback error plus release error; complete session-resource error aggregation is not claimed. Optional requestTimeoutMs is rejected by current Pi initialization if omitted; server supplies it, but direct adapter callers must do likewise pending configuration contract cleanup.

Scoped acceptance PASS; parent enterprise/isolation/deployment gates remain open.
