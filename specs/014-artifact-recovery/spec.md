# Feature Specification: Artifact access recovery

Branch: `codex/014-artifact-recovery`. Created: 2026-10-08. Status: implementation; live restoration pending valid COS credentials.

## User scenarios and acceptance
1. P1: The owner opens an existing project and creates/plans a new project using real immutable snapshots. Acceptance requires authenticated production reads and a real provider run after COS access is restored.
2. P1: When COS credentials are invalid, a user receives an actionable storage-service message; new project admission fails before business rows are created. Existing saved versions remain unchanged.
3. P2: Operators see storage readiness independently of runtime/broker readiness and can verify read/write access before deployment without exposing credentials.

## Requirements
- FR-001 Preserve exact snapshot hashes, private access, immutable publication and no fallback to stale local workspaces.
- FR-002 Classify invalid credentials, permission denial, signature rejection and missing objects into fixed codes. Never include SDK messages, signed URLs or credentials in user responses/logs.
- FR-003 COS readiness must perform a bounded real read of a registered artifact, validate its digest/metadata, cache for a configurable finite interval and serialize concurrent probes. Local development remains supported.
- FR-004 Deny new project creation and execution admission when the configured storage probe fails; health must return 503 with storage=false. Authentication remains available for diagnosis/recovery.
- FR-005 Provide a separate explicit operator preflight that verifies a new private immutable snapshot through PUT/readback and verifies all registered objects. Deployment cannot be accepted on reads alone.
- FR-006 Preserve existing data, unrelated changes and SHA-locked Pi; synchronize spec, plan, tasks and evidence; synchronize GitHub main and deploy only with verified backup/rollback gates.

## Success criteria
Exact fault regressions, full backend checks and frontend build pass. Existing screenshot project opens; a separate real project completes planning and produces a registered snapshot. Valid credentials and actual COS/provider/browser observations are required for live acceptance.

## Boundaries
Single-host deployment remains the existing architecture. This incident does not establish multi-node HA. Invalid cloud keys cannot be repaired by weakening authorization or switching to incomplete local copies.
