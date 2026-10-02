# Implementation Plan: Publish snapshots and optional functional checks
**Branch**: codex/009-publish-experience | **Date**: 2026-10-02 | **Spec**: spec.md

## Summary
Repair UTC check-result serialization first. Evolve immutable releases to explicit advisory versus required functional-check policy, then present publications as restorable snapshots. Preserve the existing Atom runtime and artifact isolation. Deployment must include configured independent content ingress, protected migration and actual recovery evidence.

## Technical Context
Python 3.12+/FastAPI/SQLAlchemy/SQLite backend, TypeScript/React/Vite frontend, pytest and actual Chromium acceptance; Linux Docker target. Existing revision ledger, ArtifactStore and release/content repositories remain the source of authority. Bounded storage reads and write-lock lifetimes follow existing infrastructure; publication does not invoke a model or regenerate content. Scope is generated static websites. No performance or high-availability claims without measured evidence.

## Constitution Check
PASS for staged implementation: preserve locked runtime/pi, existing user work, credentials and production data. Spec and tasks precede edits. Tests, frontend build, runtime integration, fault injection and live model/browser evidence are separate gates. Release migration/ingress acceptance remain required, not inferred from unit tests.

## Project Structure
- backend/app/serialize.py: explicit UTC semantics for existing persisted times.
- backend/tests/test_acceptance.py: save/reload and stale-evidence regressions.
- backend/app/migrations/: additive policy-aware release schema, exact predecessor validation and backup.
- backend/app/release_repository.py and backend/app/routers/releases.py: publication policy, atomic snapshot promotion, history and restore.
- backend/app/content_repository.py, content_service.py: retained artifact access and isolation.
- frontend/src/workspace/ContractTab.tsx, ReleaseTab.tsx, ReleaseControls.tsx: plain Chinese checks and snapshot publication experience.
- backend/tests/: HTTP, repository, migration, failure and browser coverage.
- deploy/: protected deployment and independent content ingress.

## Design
US1 normalizes UTC values before comparing or emitting acceptance timestamps; results remain honest and stale evidence remains hidden. Broader version-bound checks are tracked separately.
US2 reuses immutable registered artifacts and content policy checks. Introduce a schema version that represents advisory publication without forged verification identities, preserves existing verified release rows and enables strict policy explicitly. Preflight exact content outside the write lock, then repeat owner/head/generation checks inside the transaction. Persist idempotent receipts and audit transitions.
US3 list retained publications newest first with bounded pagination, timestamps, current-live marker and optional check details. Restore creates a new publication event from retained exact content, preserves draft head and uses expected generation to reject races. Historical preview remains owner-authorized unless deliberately published.
Content delivery reuses independent-site binding and host-only console sessions. The owner has no domain and requests IP-only access. Although IP TLS certificates now exist, different ports do not isolate cookies and one port for all projects would share browser storage. A safe IP-only design requires further work; no production activation until its cross-project and console isolation, migration and rollback tests pass. The private COS bucket supplies bytes, not an isolated browser origin.

## Delivery Sequence
1. Reproduce and fix actual 500; check save/reload regression.
2. Review policy/schema extension against all release/content invariants; record exact migration contract before coding it.
3. Implement publication, history and restore with failure tests.
4. Integrate UI using existing design tokens and real API states; desktop/mobile browser tests.
5. Full applicable gates, protected deployment, public smoke/owner acceptance and evidence reconciliation.

## Complexity Tracking
No exception to constitution. Exact schema/interface amendments are a mandatory task before US2 implementation; do not treat architectural intent as implemented functionality.

## Current worktree checkpoint
Worktree: C:/Users/Administrator/.codex/worktrees/publish-experience/atom
Branch: codex/009-publish-experience, based on b936be3. Original checkout uncommitted feature008 changes untouched. Root ignored .env in both checkouts contains private COS configuration; never print or stage it. Source currently uncommitted while integration continues.
Implemented locally: policy-aware publication/restore API, bounded generation-ordered history, retained-owner preview, reviewed v16 consumer schema gates, strict policy fixtures, COS adapter and actual private round-trip, plain-language release UI and distinct revision publication/restoration in desktop/mobile Chromium. History navigation uses native loopback HTTPS and a configured console subpath. Remaining: final broad regression gates, Linux verifier/runtime integration, COS artifact migration and target deployment. Public domain remains unresolved after clarifying that COS stores bytes but does not automatically supply website preview. User explicitly requested COS and .env configuration.

## COS process boundary
Use cos-python-sdk-v5 through an owned subprocess for each bounded operation. A parent deadline terminates and reaps a stalled SDK worker, including response trickle or retry behavior; SDK socket timeouts alone cannot provide that total lifetime guarantee. The worker receives only storage credentials through stdin, disables diagnostic payloads, refuses overwrite through a signed conditional PUT, and verifies read-after-write bytes. No per-request console/runtime secrets are passed to this process. Local and COS stores implement one snapshot port; migration verifies every old local artifact before authoritative COS reads are enabled.
