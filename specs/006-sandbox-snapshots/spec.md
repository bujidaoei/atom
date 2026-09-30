# Feature Specification: Verified sandbox snapshots

**Feature Branch**: `codex/006-sandbox-snapshots`

**Created**: 2026-09-30

**Status**: Component implemented and locally accepted; runtime integration excluded

**Input**: Enterprise trust boundary from parent 003 FR-002/003/007 and isolation contract.

## User Scenarios & Testing
### User Story 1 — Preserve verified work (Priority: P1)
As a project owner, I need transferred workspace contents to retain their exact identity without overwriting unrelated data.
**Independent Test**: Round-trip nested text, binary and empty files; compare bytes and revision identity.
**Acceptance Scenarios**:
1. Given a quiescent workspace, when transferred, every permitted regular file retains exact bytes and a verifiable inventory.
2. Given corrupted or interrupted input, receiving fails without exposing completed work or changing previous snapshots.

### User Story 2 — Reject unsafe and excessive work (Priority: P1)
As an operator, I need transfers to reject ambiguous paths, links, special files and excessive sizes before reaching sensitive data or exhausting storage.
**Independent Test**: Real filesystem and malformed-stream tests cover path escape, aliases, links, limits and exclusions.
**Acceptance Scenarios**:
1. Unsafe paths or file types fail without reading or modifying an outside canary.
2. Any configured resource limit is accepted at its boundary and rejected above it.
3. Environment files and runtime metadata are omitted on export and rejected on receive.

### Edge Cases
Empty workspace; Unicode normalization/case collisions; Windows devices/alternate streams; duplicate fields; negative or boolean sizes; excessive depth; file-as-parent conflicts; bad digests; trailing/truncated bytes; source replacement; disk-full; abrupt process death.

## Requirements
### Functional Requirements
- **FR-001**: Versioned inventory MUST identify paths, sizes and content digests with deterministic revision identity.
- **FR-002**: Only regular files transfer; links, devices, traversal, ambiguous or conflicting names MUST be rejected.
- **FR-003**: Manifest bytes, file count, depth, path bytes, individual and total content bytes MUST have validated finite limits. No decompression.
- **FR-004**: Complete verification MUST precede exposure of a completed snapshot. Normal failure cleans temporary files and leaves existing data unchanged; if cleanup itself fails, report a redacted recovery-required error and never treat the private orphan as completed.
- **FR-005**: Export MUST exclude environment files, repository/runtime metadata and dependency caches. This does not detect secrets embedded in arbitrary source.
- **FR-006**: Errors MUST identify stable reasons without file contents or credentials.
- **FR-007**: Real tests MUST establish supported platforms and recovery limits. Runtime integration remains unaccepted until separately implemented and tested.
### Key Entities
Snapshot (verified inventory, identity, files); transfer policy (operator limits); staging area (incomplete private work).

## Success Criteria
- **SC-001**: Permitted round-trip fixtures preserve every byte and repeated-export identity.
- **SC-002**: Every malformed fixture produces zero completed snapshots and unchanged outside canaries.
- **SC-003**: Limit boundaries pass, excess fails, and normal failures remove temporary output.
- **SC-004**: Evidence clearly distinguishes component, runtime, crash recovery and production acceptance.

## Assumptions
Linux exporter requires a quiescent source, with all writers stopped by its lifecycle owner. Receiver parent is trusted and tenant-inaccessible. This component does not deliver broker authorization, runtime integration, revision registration, crash janitor, quota retention or credential scanning; parent 003 retains those gates. Limits are configurable initial private-deployment defaults, not measured enterprise capacity.
