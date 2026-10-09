# Feature Specification: Generated application interaction integrity

**Feature Branch**: `codex/015-interaction-integrity`
**Created**: 2026-10-09
**Status**: Accepted — implemented, genuinely tested and deployed on 2026-10-09; see evidence.md and deployment.md
**Input**: Verify colleague screenshots reporting calculator, todo and expense buttons doing nothing, repair comprehensively, synchronize GitHub main and deploy to the existing server.

## User Scenarios & Testing

### User Story 1 - Operate saved applications (Priority: P1)
Owners can click the primary action in existing saved applications and receive the same business result as supported keyboard operation.
**Why this priority**: Users currently cannot calculate or add records by clicking.
**Independent Test**: Read the actual saved calculator, todo and expense artifacts and perform their documented actions in a real browser under delivery restrictions.
**Acceptance Scenarios**:
1. Given valid calculator operands, clicking Calculate produces the correct arithmetic result; negative decimals, invalid input, clear, history and dark styling continue to work.
2. Given a todo entry, clicking Add creates exactly one item; completion and deletion operate on that item.
3. Given an expense name and amount, clicking Add creates exactly one record and updates the total; deleting restores the total.
4. Given supported keyboard submission, pressing Enter produces the same result without duplicate records.

### User Story 2 - Trust acceptance results (Priority: P1)
The acceptance browser must exercise the same restrictions as delivered applications so a blocked primary action cannot be accepted through a more permissive environment.
**Independent Test**: A real browser executes state-changing form flows through the acceptance origin with production restrictions.
**Acceptance Scenarios**:
1. A valid client-side form action executes in acceptance, embedded preview and standalone/public delivery.
2. Invalid native form input prevents the action consistently.
3. Acceptance requirements for future applications describe observable outcomes for each primary mutating control.

### User Story 3 - Preserve isolation and user work (Priority: P1)
Interaction repair preserves project code, conversation, saved revisions and access boundaries.
**Independent Test**: Verify original artifact digests and saved project records before and after deployment; test that native forms cannot send data to another origin or to content endpoints.
**Acceptance Scenarios**:
1. Unhandled forms cannot navigate or transmit data to either same-origin or external targets.
2. Generated content retains isolated origins, no console authority and no network API access.
3. Refresh/reopen continues to load the same saved project and original artifact bytes.

### Edge Cases
Native input validation, requestSubmit, unhandled forms, hidden controls, mouse versus Enter, iframe versus top-level page, multiple browser engines, already-visible outcome selectors and duplicate submissions.

## Requirements
- FR-001 Verify the screenshot reports against actual saved artifacts; separate confirmed failures from previously passed behavior.
- FR-002 Support local form event handling in all delivery surfaces without enabling form transport.
- FR-003 Acceptance and delivery must share one execution policy with only context-specific embedding permissions.
- FR-004 Future interaction checks must cover every primary mutating action with a result-specific observable outcome.
- FR-005 Preserve immutable artifacts and existing project/conversation records; do not replace user applications or invent business data.
- FR-006 Track implementation, regression, protected backup/cutover and real acceptance separately in Spec Kit; leave unverified tasks open.

## Key Entities
Saved project and immutable artifact; generated content execution policy; revision-bound acceptance checks; protected release identity and acceptance evidence.

## Assumptions
Screenshots describe generated static apps, not Atom's own form controls. Existing project data may belong to a colleague account; read-only operator artifact access is available. Existing deployment transaction and credentials remain authoritative.

## Success Criteria
- All three reported action classes produce correct visible results by mouse and supported keyboard in real browsers.
- Native form transport remains blocked in every tested delivery context.
- Original saved artifact digests remain unchanged across deployment.
- GitHub main and feature branch contain the validated implementation; the server exposes that exact revision with healthy services and recorded acceptance.
