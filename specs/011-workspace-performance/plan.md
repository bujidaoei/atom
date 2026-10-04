# Implementation Plan: 工作区打开性能
Branch: codex/011-workspace-performance | Date: 2026-10-04 | Spec: [spec.md](spec.md)

## Summary
Eliminate replay-driven request amplification and first-render starvation. Coalesce detail refreshes with one active read and one trailing invalidation; apply every successful snapshot immediately. Add persisted eventSeq to filter historic invalidations. Abort on unmount and bound reads to 15 seconds; preserve actual failure states.
Server profile: 2.494/2.628 seconds in seven serial COS reads for three real snapshots. Reuse verified manifests only within one detail response, keyed by full immutable artifact identity. No cross-request cache or security bypass. Combine catalog head/provenance reads into one exact-schema-validated read transaction and release it before COS I/O.

## Technical Context
Python 3.12+, FastAPI/SQLAlchemy/SQLite schema18, private COS; React19/TypeScript/Vite; authenticated fetch SSE; pytest/Node tests/Playwright. Linux Docker six-service protected forward deployment. Goal: SC-001 with at most one active and one coalesced pending read. Preserve ownership, artifact validation, schema/journal checks, publication behavior and locked Pi.

## Constitution Check
Design passed: no fake business data, security bypass or Pi changes; bounded work. Implementation progress and remaining acceptance gates are tracked in tasks.md. Preserve unrelated edits. The protected deployment generated a paired temporary backup before the user subsequently requested no backups; that exact redundant directory was removed after acceptance. This explicit release-specific user instruction supersedes the constitution's normal pre-deployment backup gate for any further deployment.

## Project Structure
- frontend/src/workspace/project-loader.ts: testable single-flight lifecycle.
- frontend/src/pages/Workspace.tsx: immediate first successful rendering.
- frontend/src/workspace/useProjectStream.ts: event cursor filtering.
- frontend/src/lib/api.ts and types.ts: signal and cursor contract.
- backend/app/revisions.py: atomic read-only catalog state.
- backend/app/revision_view.py and revision_http.py: request-scoped manifest reuse.
- backend/app/serialize.py: eventSeq.
- frontend/tests/project-loader.test.ts; backend/tests/test_revision_repository.py; revision view/route tests.
- scripts/probe_workspace_latency.py: opt-in live before/after measurement.

## Delivery Strategy
Measure real browser amplification; implement and fault-test reader/controller; run backend regression, frontend build/tests, Linux integration and real browser. Commit/push, build exact source, protected forward deployment, repeat measurements and public/preview checks, then synchronize main with verified source. Retain the live candidate data and remove only the redundant pre-cutover backup after acceptance as requested. Existing broader enterprise gates are unchanged.

## Change CR-001 — dynamic preview toolbar (user addition)
Extension of existing visual system: preserve neutral surfaces, rounded segmented buttons, IBM Plex typography, icon set, spacing and existing viewport/refresh/open actions. No navigation or generation changes. Extract PreviewToolbar; observe actual container width and an inert invisible max-content copy rendered with identical full labels/URL/actions. Show labels only when that full row fits. The URL flexes/truncates in the visible row; controls never shrink or wrap. ResizeObserver covers container, font and content geometry without a hardcoded viewport breakpoint or feedback from the compact row. Validate continuous widths, same browser viewport with changing panel width, font size changes, button actions and sidebar toggles. Rebuild the release image after this user-requested addition; the earlier prepared image is not the final release.

## CR-002 design
Validate one effective budget through orchestrator, HTTP stream and sidecar. Build/planning default to 3600 seconds; model timeout inherits unless explicitly longer. Reject outside 1..7140 seconds; never clamp. Race starts and retries inherit server configuration. Override Pi provider and HTTP idle settings in memory without modifying locked Pi or persisted settings. Forward deployment captures a generation-settings whitelist from project .env before maintenance. Verify delayed HTTP, cancellation, configuration and delivery propagation.

Transport refinement: measured silent HTTP failure at 308.7s proved the independent Node fetch default. The gateway-only bundle adapter uses pinned Undici fetch and its matching Agent with per-request header/body timeout from SDK policy. This stays inside the validated gateway URL/credential/redirect boundary and does not modify locked Pi. Rebuilt bundle retains source provenance and all 1685 input hashes; actual silent-response and cancellation tests exercise it.
