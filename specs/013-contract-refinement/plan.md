# Implementation Plan: 可迭代契约与历史快照
**Branch**: codex/013-contract-refinement | **Date**: 2026-10-04 | **Spec**: [spec.md](spec.md)
## Summary
Split refinement from approval. Commit complete planning documents atomically, append immutable versions, restore by appending, and pin builds to accepted versions. Reuse publication history presentation and existing command receipts.
## Technical Context
Python/FastAPI/SQLAlchemy + SQLite; TypeScript/React/Vite; existing Node/Pi runtime unchanged except product role prompt. Target Linux Docker deployment; local Windows tests. History pages at most 20 metadata rows, full documents fetched on demand. Model calls retain bounded timeouts, cancellation, billing and durable Run events.
## Constitution Check
Pass design: preserve SHA-locked runtime/pi and original dirty workspace. Add explicit backed-up v19 migration; never startup-migrate production. Unit, integration, actual model/browser and deployment gates remain distinct. No credentials in source/evidence.
## Project Structure
- backend/app/contract_history.py: immutable snapshot persistence, CAS, context, restore and legacy baseline.
- backend/app/migrations/contract_history_v19.py: additive snapshot/approval schema, integrity guards.
- backend/app/routers/projects.py, services/orchestrator.py, serialize.py: owner routes and atomic workflow.
- frontend/src/workspace/HistoryList.tsx, ContractTab.tsx, ReleaseTab.tsx: shared history presentation and contract preview.
- frontend/src/lib/api.ts, types.ts; pages/Workspace.tsx: actions, current version and refresh.
- backend/tests/test_contract_history.py, test_contract_refinement.py; browser acceptance and specs/013-contract-refinement/evidence.md.
## Design
Snapshot stores full requirements, scope, exclusions, architecture and accepted change notes. Latest project sequence is the head; no mutable Project column. Writer transaction locks before expected-head comparison; restore appends a new snapshot and replaces requirements atomically. Initial planning commits only after Emma and Bob succeed. Existing contracts are backfilled once with honest legacy provenance.
Refinement runs Emma and Bob with current snapshot as authoritative context and explicit user change. No Alex or workspace execution. Strict parse rejects invalid complete contracts instead of silently dropping requirements. Failure preserves old head. Approval rejects notes and stale heads; persist accepted snapshot reference and use only its context in Alex build, excluding historical planning messages. General revision/race context also uses current snapshot when available.
Owner-scoped history has bounded cursor pagination. Preview is read-only. Recovery refreshes canonical project state; version-aware commands use durable replay keys. UI blocks build with unsubmitted note and blocks mutation while planning/building.
## Verification and Delivery
Validate migration backup/replay/rollback; repository CAS/immutable/cross-project/pagination; orchestrator exact context, repeated refinement and failures; real routes/receipts; build and frontend regressions. Inspect desktop/mobile real browser. Run real model refine twice, restore, build, verify actual behavior. Rehearse v18→19 on isolated candidate with unchanged backup, use protected existing deployment workflow; verify health and active revision. Record all failures honestly.

## Observed acceptance correction
The live generated application passed real audio/mute/reset behavior, but its contract scored20/29: the existing Emma instruction incorrectly assumed checks share state, while verification_observer creates a fresh context per check. Align the planning prompt with the actual observer: static initial-state exists/text checks and self-contained flow setup plus result selectors. Preserve the observer isolation boundary. Validate by real contract refinement and full generated checks. Host operator configuration must point to the schema-capable deployed source; check origin-reconcile and certificate-watch after migration.

## Delivery status
Implemented and accepted2026-10-04. Full backend regression plus final affected tests, frontend/runtime gates, live iterative contract/restore/build/audio workflow and22/22 isolated checks passed. Deployed implementation51465b5 and accepted journal; see evidence.md and acceptance.json for identities and retained failure/recovery history.

## Entry correction
User reported empty /atom after delivery: HTTP200 with zero response bytes, while /atom/ serves SPA. Add an exact308 canonical redirect in the console base. Apply with the existing host lock, identity preflight, private backup, Caddy validation, atomic reload, all-origin probes and automatic rollback; probe both redirect and nonempty SPA document. Verify anonymous desktop/mobile browser navigation. Application image/data are not changed by this ingress-only correction.
