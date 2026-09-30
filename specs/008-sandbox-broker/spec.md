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

## Key Entities
Verified artifacts must be immutable and durably acknowledged before any revision head can advance. Local storage uses exact-byte digest identity separate from the canonical revision digest; no materialization or registration is implied by storage. Missing versioned API migration and durable execution ownership are explicit prerequisites in contracts/revision-registration.md.

Verified export serializes with file operations, durably enters quiescing, exports while the worker is alive and verifies every returned byte before delivery. Repeat export is read-only and requires current authorization. An in-memory verified export is not a stored artifact or registered revision; checkpointed remains unavailable until trusted registration is implemented (contracts/checkpoint-export.md).

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
FR-006 migration prerequisite: reject unsupported API schema drift, preserve existing business rows, create a verified exclusive backup before transactional changes, and recover interrupted DDL. New scoped workspace heads start empty; legacy status cannot invent verified artifacts, accepted revisions or terminated attempts. Offline migration alone does not satisfy revision registration or application adoption.

Initial deployment is a single trusted private-team Docker host, not a hostile public multi-tenant isolation claim or HA milestone. Broker-local registry is separate from future PostgreSQL control-plane execution ownership. Paid models and full enterprise release remain parent gates. First profile only permits controlled file helpers; arbitrary user shell/background processes and dependency-network access are excluded until separately designed.
