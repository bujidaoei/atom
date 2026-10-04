# Feature Specification: Secure responsive workspace preview

**Feature Branch**: `codex/012-responsive-preview`
**Created**: 2026-10-04
**Status**: Implemented; release acceptance in progress
**Input**: Restore the preferred desktop/tablet/mobile preview inside the Atom workspace, research and implement a production-quality design, maintain Spec Kit evidence, synchronize GitHub main and deploy the result.

## User Scenarios & Testing

### User Story 1 - Inspect the saved application at three widths (Priority: P1)

An owner opens a project and immediately sees its saved application in the preview panel. Desktop uses available width; tablet and mobile retain their actual target widths even when the surrounding panel is narrow.

**Independent Test**: Open a real saved project, switch all three controls, interact with the application and inspect its actual layout width.

**Acceptance Scenarios**:
1. Given an authorized saved revision, opening Preview renders that revision in the workspace without a popup.
2. Switching desktop/tablet/mobile changes the application viewport to available width/768/390 CSS pixels without reloading or losing in-page state.
3. When the panel is narrower than a target width, the preview fits visually while retaining the target layout width; controls remain reachable and do not wrap awkwardly.
4. Keyboard users can select each mode and identify its selected state.

### User Story 2 - Preview privately and keep versions consistent (Priority: P1)

An owner can inspect a saved version without giving generated code control of Atom or allowing another preview to silently change its files.

**Independent Test**: Open different revisions and projects simultaneously; load their HTML, styles, scripts and images and attempt unauthorized access.

**Acceptance Scenarios**:
1. Generated scripts and browser storage cannot read the Atom workspace, its credential proof or another project's storage; generated content cannot invoke console mutations.
2. Opening another revision does not change the files served to an already-open view. Every resource is authorized and tied to the selected saved revision.
3. Logout, session expiry, project deletion and invalid access deny subsequent reads. Private content is never made public to recover a failed preview.
4. Only the configured Atom console may embed private previews. Other sites and other project origins cannot frame them.

### User Story 3 - Recover clearly and use a separate window (Priority: P2)

Owners see understandable empty, loading, failure and expired-access states, can retry, and can open the exact version in a separate window.

**Independent Test**: Exercise no saved files, inaccessible content service, expired access, refresh, rapid project/revision changes and the independent-window action.

**Acceptance Scenarios**:
1. Loading has a finite deadline; a load event alone is not reported as proof that the application works.
2. Refresh rechecks authorized access and preserves the selected viewport. Late responses from a previous project/version cannot replace the current view.
3. Opening a separate window preserves the workspace preview and its selected revision.
4. A blocked or unavailable preview provides a retry and actionable message without exposing credentials or low-level server addresses.

### Edge Cases

- Concurrent tabs, rapid refresh and one-use access replay.
- A new saved revision arrives while the previous preview is opening.
- Relative, root-relative and nested stylesheet/module/image paths.
- Missing/corrupt artifacts, missing entry document, restricted browser cookies and unavailable project listener.
- Browser back/reload, narrow panels, sidebar resizing, dark mode and reduced motion.
- Hostile generated messages, navigation, popup, worker and console request attempts.

### User Story 4 / Change CR-001 - Generated JavaScript syntax recovery (Priority: P1)

Investigate the real app.js:13 unexpected-closing-brace failure in project `9ac1e04b96ef41eea51add558b09d9fe`. Preserve syntax validation; correct the generation/recovery behavior based on actual stored source and events. A recoverable generated syntax error must return actionable diagnostics to a bounded repair attempt, revalidate the resulting saved files, and report success only after real validation. Unrecoverable failures must preserve honest state and concise user-facing diagnostics without temporary server paths/stacks.

Acceptance: reproduce the reported parser failure from real bytes where available; demonstrate bounded repair and revalidation; test exhaustion, cancellation and deadline paths; verify a real provider/browser workflow before marking deployed recovery accepted.

## Requirements

### Functional Requirements

- **FR-001**: Restore embedded desktop/tablet/mobile preview using the existing Atom visual system and labels.
- **FR-002**: Tablet and mobile MUST render at 768 and 390 CSS pixels; fitting a narrow panel MUST NOT change that layout width.
- **FR-003**: Viewport changes MUST preserve the current preview document and interactive state.
- **FR-004**: Private preview MUST preserve owner authorization, origin separation, source-session revocation and exact saved-version identity for every resource.
- **FR-005**: Concurrent previews MUST NOT mix revision resources or overwrite one another's access selection.
- **FR-006**: Generated content MUST NOT gain console credentials, console DOM access, console mutation authority or trusted verification authority.
- **FR-007**: Embedding MUST be restricted to the configured console; publication behavior and independent-window preview remain usable.
- **FR-008**: Empty/loading/denied/expired/unavailable states MUST be explicit and recoverable with bounded work and without automatic unbounded retry.
- **FR-009**: Refresh MUST revalidate existing access; newly saved revisions MUST acquire revision-bound access and ignore superseded asynchronous results.
- **FR-010**: Access secrets MUST NOT enter committed files, query strings, ordinary logs or user-facing error details. Authorization events retain content-free audit records.
- **FR-011**: The feature MUST pass targeted automated, real-browser security/functional and live deployment acceptance before completion is claimed.
- **FR-012**: Specification, plan, tasks and evidence MUST reflect actual work; deployment uses verified source/images and preserves current project data.
- **FR-013**: Syntax failures MUST be diagnosed from actual files and support bounded, revision-aware repair with cancellation/deadline enforcement; validation cannot be bypassed or converted to a false success.
- **FR-014**: Failure messages MUST identify file/line/actionable cause while keeping temporary infrastructure paths and raw stacks out of the main user-facing message.

### Key Entities

- **Preview view**: one owner-authorized saved revision, access lifetime and independent resource namespace.
- **Viewport selection**: desktop/tablet/mobile target and visual fit for the current panel.
- **Preview state**: empty, acquiring access, loading, displayed or failed; belongs to a specific project/revision/request generation.

## Success Criteria

### Measurable Outcomes

- **SC-001**: All three controls display the real saved application at the specified width; ten successive switches preserve an application counter/input state.
- **SC-002**: Two simultaneously open revisions retain their own HTML/CSS/script/image content through refresh and interleaved requests; unauthorized access cases serve zero private artifact bytes.
- **SC-003**: Chromium, Firefox and WebKit pass the embedded private access and console-isolation flows; desktop and narrow-panel visual acceptance has no toolbar wrapping or unintended page overflow.
- **SC-004**: An unreachable preview exits loading within 20 seconds and offers retry; no stale project response replaces the selected project.
- **SC-005**: The deployed revision passes authenticated three-mode interaction and independent-window checks; GitHub main contains the same implementation and evidence records its exact deployment.

## Assumptions

- The current supported deployment uses HTTPS on a literal IP with separate immutable project preview/public ports and existing owner authentication.
- This restores the supplied design within existing Atom components; no unrelated visual redesign is needed.
- Device modes simulate layout width, not hardware, user-agent, touch or operating-system behavior.
- Existing static-content restrictions and server-owned functional verification remain authoritative.
- High availability means bounded failure/recovery within the existing single-host deployment; this feature does not claim a new multi-host architecture or availability SLA.
