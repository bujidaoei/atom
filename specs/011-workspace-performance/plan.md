# Implementation Plan: 工作区打开性能
Branch: codex/011-workspace-performance | Date: 2026-10-04 | Spec: [spec.md](spec.md)

## Summary
Eliminate replay-driven request amplification and first-render starvation. Coalesce detail refreshes with one active read and one trailing invalidation; apply every successful snapshot immediately. Add persisted eventSeq to filter historic invalidations. Abort on unmount and bound reads to 15 seconds; preserve actual failure states.
Server profile: 2.494/2.628 seconds in seven serial COS reads for three real snapshots. Reuse verified manifests only within one detail response, keyed by full immutable artifact identity. No cross-request cache or security bypass. Combine catalog head/provenance reads into one exact-schema-validated read transaction and release it before COS I/O.

## Technical Context
Python 3.12+, FastAPI/SQLAlchemy/SQLite schema18, private COS; React19/TypeScript/Vite; authenticated fetch SSE; pytest/Node tests/Playwright. Linux Docker six-service protected forward deployment with paired backup. Goal: SC-001 with at most one active and one coalesced pending read. Preserve ownership, artifact validation, schema/journal checks, publication behavior and locked Pi.

## Constitution Check
Design passed: no fake business data, security bypass or Pi changes; bounded work. All implementation and acceptance gates remain pending. Preserve unrelated edits. Deploy clean traced source only after tests and protected backup/preflight.

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
Measure real browser amplification; implement and fault-test reader/controller; run backend regression, frontend build/tests, Linux integration and real browser. Commit/push, build exact source, protected forward deployment, repeat measurements and public/preview checks, then synchronize main with verified source. Existing broader enterprise gates are unchanged.
