# Feature Specification: Isolated sandbox broker
Branch `codex/008-sandbox-broker`; created 2026-09-30; status **in progress, not accepted**.
Input: parent 003 isolation/execution contracts; actual container quota, snapshot and runtime lifecycle evidence.

## User Scenarios & Testing
### US1 — Authorize only the intended work (P1)
Operator issues a finite permission for one organization/project/run/attempt and input revision. Runtime cannot alter it to access another workspace or choose host resources.
Independent acceptance: valid authorized file operations succeed; forged/expired/wrong-purpose/wrong-scope/revoked permissions produce no container or file mutation.

### US2 — Bound and recover execution (P1)
Operator can cancel work or restart the service without leaving indefinite execution or accepting stale results.
Independent acceptance: real timeout/cancel/restart/daemon failure tests preserve durable ownership and confirm termination before replacement. Unknown termination fails readiness and dispatch.

### US3 — Preserve verified work through existing tools (P1)
Project owner uses current write/read/edit/glob/grep and recovery, with verified snapshots preserving results across isolated attempts.
Independent acceptance: actual Pi and file tools through broker/containers; byte-exact input/output snapshots; failed or stale promotion preserves prior revision; cancellation reports uncheckpointed data loss accurately.

### Edge Cases
Duplicate creates, same identity/different grant, lost create response, worker or broker crash, expiry during operation, stale fencing token, output flooding, symlink/path attacks, quota/OOM, interrupted checkpoint, previously acquired sandbox not released, daemon unavailable, partial adoption/migration.

## Requirements
- FR-001: Signed permissions MUST bind organization, project, run, attempt, input revision, fencing token, supported profile and finite lifetime. Verification MUST reject malformed/forged/expired/future/wrong-purpose scopes without side effects.
- FR-002: Service authentication and permission-signing keys MUST be separate from runtime/session/model credentials. No platform secret, Docker authority, host path, image or resource flags may be supplied by the workload.
- FR-003: Ownership intent MUST be durably recorded before creation; duplicate equivalent requests return same attempt, conflicts fail. Revocation/current fence/state MUST be checked on every operation.
- FR-004: Actual OS/resource/egress limits MUST apply. Each attempt has a finite independent lifetime and bounded operation input/output/deadlines.
- FR-005: Cancellation/restart MUST reconcile owned containers, persist confirmed or unknown termination, prohibit further mutation and reject dispatch while unsafe. Orphan removal MUST follow durable discovery and full-ID ownership verification; pending observations survive deletion/confirmation crashes without fabricating grants or revisions. Versioned registry migration MUST preserve prior ownership and revocations or roll back completely.
- FR-006: Normal completion MUST quiesce writers while alive, verify export, fence revision registration, then destroy. Failure preserves previous committed revision; no implicit publication in destroy.
- FR-007: Own runtime and existing file tools MUST use the broker; production MUST fail closed without it. Explicit development local mode remains visibly non-isolated.
- FR-008: Real integration, fault injection and deployment migration evidence MUST precede acceptance. No component test may close whole feature.

FR-007 runtime acknowledgement: Node MUST correlate confirmed completion to the trusted API-attempt/workspace/broker-attempt/grant/deadline and a valid registered receipt. HTTP 200 with cancelled/failed/timed-out outcome or missing receipt is not successful completion.

FR-007 completion HTTP: complete/cancel requests MUST derive their target solely from verified execution-purpose claims and compare every immutable persisted binding plus current ownership before effects. Only confirmed closed results may return success; transport or storage failures must not be presented as accepted output.

FR-007 completion authority: runtime completion MUST use an independently scoped execution capability; sandbox grants and administrative credentials must not authorize that boundary. Purpose, exact persisted scope, owner, fence and deadline must be checked before action. Issuance alone is not completion acceptance.

FR-007 lease preparation: a ready runtime lease MUST derive from a persisted reservation and verified immutable base, bind the actual broker identity, and pass a fresh dispatch check. Ready replay must not reseed; preparation failure must never return a lease or imply successful completion.

FR-005 cancellation ordering: committed API cancellation MUST precede administrative revocation; confirmed closure MUST follow verified broker termination. Transport uncertainty or caller cancellation must not release the active slot. Concurrent already-closed outcomes and receipts remain unchanged.

FR-005 recovery visibility: trusted owner-checked cleanup reads MUST remain available after cancellation, expiry, registration and closure without granting dispatch, releasing ownership or changing any persisted outcome. Cancellation returns committed cleanup identity; closed-attempt retries preserve successor state.

FR-005 terminal recovery: the coordinator MUST durably decide its intended outcome before releasing the worker. A pending decision is not a terminal result and retains ownership; recovery repeats verified termination before closure. Explicit cancellation may override nonclosed success intent.

FR-006 completion recovery: persisted receipt recovery MUST compare the current broker checkpoint digest and actual immutable artifact before skipping export/confirmation. A cancellation committed before final success closure MUST prevent succeeded outcome even when a revision already exists.

FR-006 registration semantics: a durable checkpoint, a successfully terminated execution and independently accepted product output are separate facts. A later failed/cancelled run must preserve any committed revision without being reported successful. Lost acknowledgements must resolve an immutable receipt; retries must not advance a newer head. Unknown termination retains ownership until reconciliation confirms release.

FR-006 migration prerequisite: reject unsupported API schema drift, preserve existing business rows, create a verified exclusive backup before transactional changes, and recover interrupted DDL. New scoped workspace heads start empty; legacy status cannot invent verified artifacts, accepted revisions or terminated attempts. Offline migration alone does not satisfy revision registration or application adoption.

## Key Entities
Trusted control-plane transport cannot infer durable success from HTTP headers or automatically replay uncertain mutations. It must verify complete bounded responses, exact attempt/deadline/version and both archive/semantic digests. Administrative credentials/signing authority stay outside runtime leases. Execution intent must be durably reserved before provisioning and later bound to one broker identity. Repository and real component integration now exercise that ordering; production coordinator/application adoption remains unaccepted.

Administrative checkpoint transfer requires independent admin credentials plus a scoped grant; runtime tokens alone cannot export or confirm. Large export responses retain the shared transfer slot through bounded delivery and release it on transport failure. A partial response is not durable storage or registration acknowledgement. The caller must obtain an actual API receipt before asserting a registered digest over the administrative confirmation route.

Verified artifacts must be immutable and durably acknowledged before any revision head can advance. Local storage uses exact-byte digest identity separate from the canonical revision digest; no materialization or registration is implied by storage. Offline API migration and trusted execution/revision repository now exist; production adoption remains an explicit prerequisite in contracts/revision-registration.md.

Verified export serializes with file operations, durably enters quiescing, exports while the worker is alive and verifies every returned byte before delivery. Repeat export is read-only and requires current authorization. An in-memory verified export is not a stored artifact or registered revision. Explicit trusted confirmation after durable registration rechecks export bytes/scope/version and current authority before checkpointed; it never implicitly releases the worker (contracts/checkpoint-export.md).

Runtime broker adapter is bound to one trusted pre-seeded lease and contains no administrative credentials. Acquisition verifies live ready status; failed acquisition attempts cleanup. Unknown transport outcomes prohibit new calls; release succeeds only with matching confirmed termination. Scoped release may repeat cleanup of its own immutable attempt despite revocation, but cannot act on a successor or grant new authority (contracts/runtime-adapter.md).

HTTP seed/file intake authenticates before consuming large bodies, checks current ownership before intake and dispatch, and serializes large transfers with immediate busy rejection. Admin seed credentials and runtime grant authority are distinct. Known operation failures remain explicit outcome values; transport success alone is not business success (contracts/runtime-http.md).

Input initialization requires a verified ATOMSNAP1 stream matching the grant's exact base revision. Only provisioning attempts may receive it; no merge into an existing workspace. Ready is committed only after successful validation/promotion and a fresh ownership/version check. Failed or uncertain imports retire the attempt; ready is not output revision registration (contracts/seeding.md).

File-operation retries must bind an operation ID to the exact request and current authorized attempt. Completed responses may be reused within bounded durable storage; uncertain effects must not be replayed. Revocation/expiry deny late completion and recovery retires prior workers before new dispatch (contracts/operation-receipts.md). This component does not establish end-to-end runtime acceptance.

Grant, broker attempt registry, operation receipt, immutable snapshot, registered revision, terminal outcome with termination status.

## Success Criteria
- SC-001: All negative authorization cases cause zero container/file effects.
- SC-002: Real duplicate delivery and restart tests retain one owned attempt; stale operations cannot register output.
- SC-003: Existing real Pi/file-tool scenarios pass through actual containers with exact snapshots.
- SC-004: Cancellation/timeout and orphan reconciliation are measured against configured deadlines; unknown outcomes are visible and prevent unsafe replacement.

## Assumptions
Initial deployment is a single trusted private-team Docker host, not a hostile public multi-tenant isolation claim or HA milestone. Broker-local registry is separate from future PostgreSQL control-plane execution ownership. Paid models and full enterprise release remain parent gates. First profile only permits controlled file helpers; arbitrary user shell/background processes and dependency-network access are excluded until separately designed.

FR-007 lifecycle ownership: one sandbox acquisition and one final checkpoint MUST cover the entire model recovery sequence. Work results must not return before verified completion and cleanup; failures preserve their original and cleanup causes.

FR-007 external scope: ProductAgentRuntime MUST reject a different run before session effects and MUST NOT destroy a sandbox owned by an outer execution lifecycle during internal recovery or failure.

FR-007 production selection: production runtime MUST require broker mode, configured trusted origins and matching ready leases, with no local fallback. Terminal result delivery must follow registered completion and expose the verified revision receipt.

FR-007 API acknowledgement: leased runtime success MUST match an owner-scoped durable confirmed successful receipt before the API yields the terminal result. Missing, mismatched or uncommitted runtime receipts must be rejected.

FR-006 workspace identity: new committed projects and race heats MUST obtain an owner-checked durable workspace identity without fabricating artifact or revision evidence. Concurrent retries preserve identity and existing execution/head state; foreign heat membership is denied.

FR-006 initial import: trusted quiescent legacy workspaces must be exported and stored as verified immutable bytes before root registration. Exact replay must preserve identity; changed input must not reset an existing root or head. Import must reject source roots containing control-plane database or artifact storage.

FR-005 startup recovery: before broker-backed API admission, interrupted attempts must be enumerated from the durable ledger and revoked with separately confirmed termination. Preserve already-decided outcomes and receipts; absence of a success decision is not success. Capacity exhaustion, timeout or uncertain termination must prevent readiness.

FR-007 application startup: production requires broker mode and explicit separate broker/completion credentials. The API must hold exclusive host-local database ownership while recovering and serving, refuse unsafe or unmigrated databases, expose scoped completion/cancellation only after recovery, and reject dispatch without a prepared lease. Health must include authenticated broker readiness.

FR-006 committed read identity: validation and preview must identify the registered immutable revision whose bytes they read. Owner-scoped reads must not silently fall back to the old mutable workspace. An explicitly expected revision mismatch is a conflict; temporary read extraction must be cleaned on normal and exceptional exit.

FR-006 preview/file adoption: broker-mode preview and source-file routes must read committed artifacts and identify the revision in response headers. Missing service/version or corrupt artifacts must not fall back to mutable files. Draft previews, including heats, require ownership even when the project has a published slug.

FR-006 catalogue consistency: broker-mode project detail and race responses must derive file lists/counts/bytes and preview availability from verified committed manifests, expose revision identity and never list uncommitted host files. An uninitialized scope reports revisionId=null and an empty list. File timestamps must identify their actual source rather than inventing filesystem modification times.

FR-007 application dispatch: after committing the current Run, broker orchestration must establish workspace identity, import a real initial source only when no head exists, reserve durable dispatch authority before provisioning, and deliver the prepared lease. Later turns must seed from the registered head. Successful engineering turns must validate the exact returned committed revision, not the legacy directory. Failure/timeout/cancellation must request confirmed scoped cleanup and preserve unknown ownership. The application/broker profile permits at most 7200-second capabilities, with 60 seconds reserved beyond the turn budget for completion/cleanup.

FR-005 active-model interruption: the runtime must distinguish explicit cancellation from its own elapsed deadline in error status, never emit a result for either, and allow independent cleanup to finish. API Run and single-project planning/build status must preserve cancelled/timed_out rather than collapse them to ordinary failure. Unregistered writes must not replace the last committed version.

A deadline observed after durable artifact registration but before the runtime response MUST prevent a successful Run/project outcome. The already committed revision and receipt remain valid; execution cleanup success is distinct from timely run completion.

Cancellation request lifetime MUST NOT own cancellation cleanup. Disconnecting either the initiating caller or a duplicate waiter must not send another cancellation into the run cleanup. Shutdown must await owned cleanup even after the run job has left its job map.

FR-006/FR-008 refinement: enterprise acceptance must bind exact artifact, contract and trusted verifier identity. Publication/adoption require fenced immutable revisions and atomic release pointers. Timestamp/client-reported checks cannot authorize release. contracts/revision-release.md defines the unimplemented requirements.

FR-006 next-version migration prerequisite: verified backups must retain the exact supported source schema (baseline or v1), include committed WAL, exclude concurrent writers during capture, and refuse overwrite/drift. Backup verification must explicitly select the expected version rather than accepting any version.

FR-006 migration extension: explicit target v2 may add verification/release identity tables while preserving exact v1 business and journal records. Original evidence is not backfilled or promoted. Runtime startup remains v1-only until repositories, verifier and application adoption pass their gates.

Verification contract identity includes ordered requirements/checks/setup, title/detail, selectors and exact input/expected text. Strict versioned encoding rejects unknown fields, duplicate keys and invalid Unicode; it must not silently repair or discard checks. Complete results require exact unique check identities and actual booleans.

Verification intent reservation must capture the stored project contract under the same writer transaction as owner/current-head/idle checks. Exact request replay preserves original identity and deadline; replay is historical evidence, not renewed dispatch permission.

Verification result registration derives outcome/counts from exact complete coverage of the captured contract. A first report outside the original time interval is rejected. Exact historical replay retains the original timestamp; changed report content conflicts. Persisting a report does not publish or prove verifier authority.

Verification interruption must persist cancelled/timed_out separately from observed check results. A report and interruption racing for the same request can commit only one immutable terminal result. Expiry inventory must be bounded and reject capacity overflow without partial mutation.

Release metadata promotion must recheck owner, idle main workspace, expected head, current contract, passing evidence, policy and runner in the same transaction that advances the publication generation. Release record, pointer and idempotency receipt commit together; historical replay must not repromote old content.

Unpublish must compare expected release and generation, atomically disable visibility and save an idempotency receipt, preserving artifact/history. Exact historical replay cannot disable a subsequently published release.

Pinned published artifact lookup requires an active current publication and authorization under both the current release audience and the selected historical release audience. Unpublish denies even owner-facing publication paths; draft preview remains a separate route.

Published materialization must verify actual immutable storage bytes against recorded semantic digest and size, never fall back to legacy directories, and clean private temporary output on normal/error exit. Recheck current visibility after storage IO before yielding a captured version.

Published view materialization must bound concurrent in-memory snapshot reads and extraction. Current single-process profile permits one active view with a three-second admission wait; capacity is released after normal/error exits. Reauthorize the pinned release after extraction before returning it.

T017 content isolation refinement: generated content must use a dedicated content site and durable per-version host binding. Root-relative resources must resolve within the same pinned artifact. Console credentials and direct DOM-based acceptance must not cross the content boundary. See contracts/content-origin.md; requirements remain unimplemented.

Content origin binding uses an immutable opaque route identity scoped by project and release, unique per release; invalid route syntax and cross-project mapping must fail at the database boundary. Offline migration must preserve prior version definitions and journal history.
