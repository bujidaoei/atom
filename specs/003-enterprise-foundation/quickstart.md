# Enterprise verification protocol — design, not executed results

This is the acceptance procedure to implement. Current code does not yet satisfy it. Use isolated test services, synthetic credentials and real generated outputs; deterministic failure fixtures test failure handling and must never be represented as real business completion.

## Before running
Record git revision, dirty diff hash if any, Pi lock verification, OS/runtime versions, database schema version, service image digests, effective policy and resource limits. Create two test organizations, two projects each, five role presets and synthetic secrets outside tracked files. Use a separate test database/storage root and controlled network targets; never point fault injection at production.

## Security (US1)
1. Configure a managed provider and a controlled capture endpoint. Change only a user's endpoint and request model discovery, planning, build and race. Assert the managed synthetic secret never reaches the capture endpoint and a structured missing/forbidden-connection error results. A complete user-owned connection must work using its own credential.
2. Test approved public and internal connections independently, with redirects and address changes. Denied connections must be blocked at network use, not only saved-config validation.
3. Render a controlled generated page under preview and public hosting. Attempt console API writes, parent DOM reads and other-project reads from iframe and top-level contexts. All fail, while authorized preview/app flows still work.
4. Run every resource endpoint through the role/tenant matrix. Revoke membership during a long run; subsequent sensitive operations must fail without exposing data.
5. Start isolated worker with harmless canary files outside its workspace. Prove it cannot read the host/other-project canaries or inherited platform environment, exceed configured limits, or reach forbidden network targets. Prove approved tools still function.
6. Boot production configuration with each required secret or origin missing. Assert startup/readiness fails for the correct reason, with no secret content in logs.

## Durable execution and budget (US2)
Use real two-worker execution against the selected transactional database. Inject 100 duplicate command deliveries, 20 process exits and a stale worker return after lease expiry. Assert one active owner and one terminal outcome per attempt, no duplicate external operation, bounded recovery and ordered event resync. Show old worker writes rejected. Stop during provider timeout; reconcile unknown outcome instead of counting success. Run ten simultaneous reservations against a deliberately tight budget; verify ledger totals, releases and late-charge variance handling.

## Evidence and release (US3)
Build an actual small app with a real model, such as a task list with persistence, filtering and validated input. Define its acceptance contract before generation. A separate runner exercises its browser and API behavior, writes exact artifact/contract/environment digests and retains failed attempts. Submit forged client evidence and stale evidence after a code/config change: neither qualifies for release. Promote valid artifact, inject upload/probe/database failure before pointer switch, and verify the previous release remains usable. Verify successful deployment by exact artifact identity plus real user flow.

## Collaboration and portability (US4)
Use an explicitly designated test repository. Import an existing branch, make conflicting edits on both sides and confirm conflict is surfaced without overwriting. Create a reviewable change; test disallowed direct protected-branch push and unauthorized release. Export one accepted revision and rebuild in a clean environment with documented configuration. Compare artifact manifest and test behavior; account for declared nondeterministic build metadata rather than ignoring differences.

## Operations and recovery
Before implementing the tmpfs broker, use one disposable nonroot/no-network container with finite lifetime and no host mounts. Create synthetic regular files, finish all controlled writes, export with the actual snapshot library while PID 1 remains alive, and verify through the host receiver. Stop/restart the container and assert tmpfs contents disappear. Restore the verified stream into a new workspace and compare exact revision and file bytes. Remove the container and verify absence. This demonstrates transfer ordering only; no uncontrolled descendant writer, broker restart, durable fencing or live agent acceptance is implied.

Measure p95 non-generation latency at the specified 50-member/10-run workload, including database and storage use. Kill one worker and one control-plane replica separately; then test host loss only in an isolated environment with actual redundant fault domains. Restore encrypted backup into a clean environment and run the same critical flows. Record measured RTO/RPO, key availability and external effects not restored. A single-host restart test cannot close the HA gate.

## Evidence format and closure
Every record includes test ID, requirement IDs, revision, environment, command/procedure, start/end, expected and actual result, artifact refs, sanitized diagnostics and pass/fail/blocked. Never turn unavailable infrastructure, missing credentials or unsupported test conditions into pass. Timestamps/logs/screenshots and machine-readable assertions must agree. Only then update the corresponding task checkbox; a whole story stays open until its independent test and all mandatory gates pass.
