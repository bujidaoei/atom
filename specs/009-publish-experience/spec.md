# Feature Specification: Publish snapshots and optional functional checks

**Feature Branch**: `codex/009-publish-experience`
**Created**: 2026-10-02
**Status**: Partial implementation; IP-only isolation and production acceptance pending
**Input**: Repair check HTTP500, restore simple publication, make publishing a comprehensible history of restorable published snapshots; retain Atom runtime.

## User Scenarios & Testing
### User Story 1 - Run understandable functional checks (Priority: P1)
Creators can check the actual generated page and distinguish feature failures from service failures.
**Why this priority**: Ordinary generated projects currently encounter HTTP500.
**Independent Test**: Run checks after generation, save and reload actual observations.
**Acceptance Scenarios**:
1. Given generation history, completed checks save and reload without HTTP500.
2. Given newer saved content, old results are not presented as current evidence.
3. A service failure says checking did not finish, not that the application failed.

### User Story 2 - Publish directly (Priority: P1)
Owners publish a saved website without separately completing functional acceptance.
**Why this priority**: Isolated-workspace mode currently blocks publication.
**Independent Test**: Publish an existing saved page without passing checks and compare the public page to the selected saved content.
**Acceptance Scenarios**:
1. Default publication succeeds with one primary action and no mandatory functional-check step.
2. Failed or unavailable optional checks do not block publication or become a false verified claim.
3. Concurrent edits and failed publication preserve the previous live version.
4. Anonymous and foreign owners cannot change publication; public application content cannot exercise console authority.

### User Story 3 - Browse and restore published snapshots (Priority: P1)
Owners see the current live version and a chronological publication history, preview any retained historical publication and restore it.
**Why this priority**: The user explicitly defines the publication page as a snapshot and recovery experience.
**Independent Test**: Publish two distinct versions, preview and restore the first, reload and compare the live page and history.
**Acceptance Scenarios**:
1. Every publication creates a durable saved version, timestamp and public link.
2. The main page uses plain Chinese states such as current online, unpublished and unpublished changes; hashes and internal infrastructure terminology are not primary content.
3. Restoring a historical publication switches the live content without overwriting the editing draft, and creates a new traceable history event.
4. Unpublish removes public access; retained history remains available to the owner.
5. Missing/corrupt historical content is clearly identified and cannot replace a healthy live version.

### Edge Cases
Missing entry page, corrupt artifacts, active edits, double clicks, stale selections, interrupted requests, unavailable checker, old evidence, historical projects and public URLs, failed migration, unsafe content and cross-owner requests.

## Requirements
### Functional Requirements
- **FR-001**: Explain functional checks in plain Chinese; distinguish unfinished checking from failed assertions.
- **FR-002**: Default publication must not require passing optional functional checks; retain mandatory ownership, content integrity and isolation.
- **FR-003**: Publish exactly the selected saved version, never a stale working directory.
- **FR-004**: Provide chronological published snapshots, historical previews, live restoration and unpublish with concurrent-change protection.
- **FR-005**: Prioritize the public link, current online version, publish update and history; hide internal IDs and diagnostic details behind optional disclosure.
- **FR-006**: Preserve project data, editing drafts and SHA-locked Atom runtime.
- **FR-007**: Keep research, design, tasks and real evidence synchronized in Spec Kit; never mark untested delivery accepted.
- **FR-008**: Back up before deployment, test failure recovery and verify actual public delivery on desktop and mobile.

### Key Entities
Saved version: immutable content. Functional check: version-bound observations and outcome. Publication snapshot: owner, saved version, publication time and address. History event: publish, restore or unpublish with durable ordering. Policy: optional functional quality versus mandatory safety.

## Success Criteria
### Measurable Outcomes
- **SC-001**: A regression reproduces the reported HTTP500 and proves results save and reload after correction.
- **SC-002**: An owner publishes a saved page using one primary action without manual prerequisite checks.
- **SC-003**: Initial publication, update and restoration serve exactly the selected content; injected failures preserve the prior live version.
- **SC-004**: Real-browser tests verify history, restore, no console authority for public content and no horizontal overflow on desktop/mobile.
- **SC-005**: Deployment has a traceable commit, protected backup, verified recovery path and real evidence.
- **SC-006**: Real browsers prove that public and draft pages preserve their own native storage across reload/update/restore and cannot access console authority or another project's storage. A controlled browser check proves results belong to the exact owner-initiated saved revision and rejects forged page submissions.
- **SC-007**: A recovery drill shows that an unchanged post-cutover candidate can restore the exact old pair, while an injected durable user write blocks old-schema rollback before the live candidate is replaced and retains that write for forward recovery.
- **SC-008**: During protected activation, real certificate-verified project content routes pass legacy import readiness while the console origin rejects writes; the candidate baseline is sealed before console traffic is enabled, and a failed phase restores the old pair or retains the candidate if new durable writes appeared.
- **SC-009**: After an old-schema rollback is refused because a real owner release changed the candidate ledger, a protected forward deployment starts from that retained ledger, keeps the release/history and draft intact, preserves each project's HTTPS origin, and proves a further owner write and public read through the new image. A failed forward phase preserves the last serving data generation.

## Assumptions
- Scope is the current generated website product, not arbitrary backend hosting.
- Restoring a publication changes the public version and preserves the editing draft. It does not roll back browser-local or external service data.
- Existing feature-008 uncommitted work stays in the original checkout; this isolated checkout starts from committed source.
- Broader feature-008 infrastructure tasks remain separately open; this feature does not claim all enterprise work complete.

## COS amendment
- **FR-009**: Persist immutable publication content in configured private Tencent COS and publication metadata in the mounted server database. Secrets stay in ignored environment files; checked-in examples have empty credentials. Storage failure must not change the live publication.
- **FR-010**: Public generated JavaScript, including legacy `/p/{slug}` links, must remain isolated from the console and other projects' browser storage. The user has no domain and prefers the server IP; deployment must establish and test a safe IP-only isolation architecture or keep public activation pending. A different port alone does not isolate HTTP cookies.
- **FR-011**: Draft preview and functional checks must execute generated JavaScript outside the console origin. The owner must retain native scripts and browser storage in preview; a saved race-heat revision must also open through the same owner-scoped isolated preview while an unsaved heat cannot execute generated code on the console origin. An isolated server browser must collect real observations for a specific owner-initiated, version-bound check run. Generated pages cannot submit their own check results.
- **FR-012**: When using same-IP HTTPS ports, every authenticated console API request must require a durable console-origin proof in addition to its HttpOnly session cookie. Project preview/public origins must be stable, unique and never reassigned across projects or releases; capacity exhaustion and ingress failure must leave the previous publication intact.
- **FR-013**: The trusted verifier coordinator must start independently of the console with an exact worker image, private control credential and resource-bounded browser workers. It must share the authoritative ledger and private artifact store, publish no host port, and be reachable from the console only on a dedicated Docker bridge at an explicitly allowed service origin. It must report unhealthy if its daemon lease is lost, release its lease on orderly shutdown and reconcile orphan workers before a successor accepts work. A protected deployment must start and validate it before enabling owner-initiated checks.
- **FR-014**: A schema-changing operational rollback to preserved old containers may proceed only when the system proves that the candidate has no unmerged durable user writes. After such writes, preserve the live candidate and require a data-reconciling forward recovery instead of silently re-exposing the old database. This operator safety gate must not add prerequisites to a user's ordinary snapshot publish or historical-version restore.
- **FR-015**: Deployment must preserve the real HTTPS readiness check for each legacy publication while preventing authenticated console writes until legacy import and a durable candidate baseline complete. A failure in this interval must not expose an unsealed writer or promote an older database over unmerged user state.
- **FR-016**: After FR-014 refuses an old-schema rollback, the operator must have a protected forward deployment that takes the current candidate ledger and broker registry as its sole data source. It must quiesce every writer, make and verify a new paired backup, prepare a separate candidate generation, preserve immutable artifacts, COS bindings and never-reused project origins, and verify exact image/schema compatibility before exposing the replacement. Failure must resume the last compatible serving generation without discarding committed owner work. A future schema change requires its own explicit migration and cannot reuse the schema10-to-18 import path.
