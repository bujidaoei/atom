# Feature Specification: Functional check repair

**Branch**: `codex/010-acceptance-fix`
**Date**: 2026-10-02
**Status**: Implemented and verified in production

## User Scenarios & Testing

### User Story 1 - Save real functional checks (P1)

A creator runs the checks listed for a generated website and sees the saved result after reopening the project.

**Independent test**: Run a check after generated work, then reload the page.

**Acceptance scenarios**:
1. A completed check is saved and reloaded without HTTP 500.
2. Newer generated work makes an older check result stale without erasing its history.
3. A service failure is shown as an unfinished check, not as a failed website assertion.

### User Story 2 - Understand the action (P1)

A creator sees “检查功能” and plain-language pass/fail wording instead of unexplained “运行验收” terminology.

**Independent test**: Use desktop and mobile browsers to run checks, reload, and inject a failed save response.

## Edge Cases

Saved timestamps without timezone information, in-memory timezone-aware timestamps, stale results, a failed save, and a previous valid result shown alongside a new service failure.

## Requirements

- **FR-001**: Compare persisted and new generated/check times as the same UTC timeline.
- **FR-002**: Return a timezone-explicit result time and retain old evidence without presenting it as current.
- **FR-003**: Describe the check action, actual assertion result and service failure distinctly in Chinese.
- **FR-004**: Keep the existing publication policy and data schema unchanged in this independently deployable repair.

## Success Criteria

- **SC-001**: Real HTTP/SQLite checks save and reload for build, revise and race generation phases.
- **SC-002**: Real desktop and mobile Chromium runs complete a functional check and classify injected service failure correctly.
- **SC-003**: The exact committed image passes schema-preserving production preflight and the target check no longer returns HTTP 500.

## Assumptions

This is the independently releasable check defect from the broader `009-publish-experience` feature. Publishing snapshots and COS/ingress migration remain open in that feature; this stage does not claim to enable publication.
