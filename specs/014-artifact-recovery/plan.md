# Plan: Artifact access recovery

## Context and constitution
Python/FastAPI, bounded COS SDK subprocess, SQLite revision ledger, existing protected forward deployment. Preserve private immutable COS authority and locked Pi. Work started from origin/main 219784c; pre-existing workspace changes preserved in stash.

## Design
1. Map SDK service status/code pairs to fixed ArtifactError codes at the worker boundary; use the same allowlist in the parent protocol and a shared user-facing message mapper. Do not serialize raw SDK diagnostics.
2. StorageReadiness owns a bounded COS client (4-second subprocess lifetime), SQLite read-only selection of the smallest registered artifact, metadata verification, monotonic TTL and a lock. Missing inventory fails closed. Cache is process-local, never a permanent health assertion; first check probes immediately and concurrent callers share serialized state.
3. Attach readiness to application/execution resources. Health uses a thread so filesystem/SDK work never blocks the event loop. Creation checks before any insert and execution checks before reservation/provision. Retain API auth/diagnostics while storage is degraded. Increase Docker health timeout to cover the bounded probe plus runtime/broker checks.
4. An explicit storage preflight generates a uniquely identified valid snapshot, checks immutable upload/readback, then runs existing full registered-object verification. It writes only private content-addressed probe objects; no business ledger rows or user workspace mutations.
5. Deploy only after credential repair, exact image tests, quiesced paired backup and storage preflight. Use existing host-local protected forward transaction; do not bypass a COS gate. Verify screenshot owner flows with real browser and provider. Failure leaves live tasks open.

## Implementation order
Document evidence → fault tests → error classification/readiness/admission/preflight → regression/build → main synchronization → target image tests → credential/preflight/backup → cutover → live acceptance.
