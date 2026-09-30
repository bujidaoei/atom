# Feature Specification: Runtime sandbox ownership

**Branch**: `codex/007-sandbox-lifecycle`
**Created**: 2026-09-30
**Status**: Implemented and locally accepted within adapter ownership scope
**Input**: Parent isolation lifecycle finding from 42419d9; enterprise bounded resource ownership.

## User Scenarios & Testing
### US1 — Release resources on every exit (P1)
As an operator I need successful sandbox acquisitions released even if initialization, model work or session cleanup fails.
Independent test: inject initialization failure after actual acquisition, observe exactly one release; repeat for success and operation failure.
Acceptance: every successful acquisition leads to one awaited release attempt; failed acquisition never causes a guessed release. Tools-disabled runs allocate nothing.

### US2 — Preserve failure evidence (P1)
As an operator I need a release failure to prevent false success, without losing an earlier operation failure.
Independent test: operation and release fail together; both original errors remain available with a stable outer error. Successful operations with failed release fail overall.
Acceptance: release is awaited before run resolves/rejects, no hidden retry or success after failed release.

### Edge Cases
Early model/tool initialization failure, cancellation, disposal failure, simultaneous work/release failures, thrown non-Error values, failed create with unknown external side effects, recovery re-entry.

## Requirements
- FR-001: Every acquired sandbox MUST have one ownership scope covering all subsequent initialization/execution/cleanup.
- FR-002: Release MUST be awaited exactly once per successful acquisition, regardless of operation outcome; no release if acquisition fails or tools are disabled.
- FR-003: Release failure MUST fail the operation; simultaneous failures MUST retain both causes without concatenating arbitrary error details into the outer message.
- FR-004: Existing real file tools and Pi session recovery MUST continue working; locked Pi remains unchanged.
- FR-005: Evidence MUST distinguish an attempted adapter release from verified container termination or durable recovery.

## Key Entities
Owned sandbox ID; operation result/error; release result/error. No new persistent entity.

## Success Criteria
- SC-001: All defined exit-path tests observe exact acquisition/release counts and awaited ordering.
- SC-002: Real Pi recovery/file-tool regression passes with byte-exact workspace results.
- SC-003: No test-only production behavior, Pi changes or broker acceptance claims.

## Assumptions
This corrects runtime ownership, not Docker termination guarantees. Adapter operations remain responsible for finite deadlines; an acquisition that creates external state but rejects requires broker idempotency/reconciliation. Destroy remains cleanup, never implicit checkpoint/publication. Parent T027 retains broker, snapshot registration, lifecycle recovery and production gates.
