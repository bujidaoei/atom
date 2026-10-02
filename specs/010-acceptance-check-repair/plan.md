# Implementation Plan: Functional check repair

**Branch**: `codex/010-acceptance-fix` | **Spec**: `spec.md` | **Date**: 2026-10-02

## Summary

Normalize SQLite and in-memory timestamps at the acceptance serialization boundary. Clarify the action and failure states in the current UI. Release as a schema-preserving image change while broader publication work remains gated.

## Technical Context

Python 3.12, FastAPI, SQLAlchemy and SQLite; React/TypeScript and Vite; pytest and Chromium. Existing server is schema10 and uses the SHA-locked Atom runtime. No migration or publication configuration changes in this stage.

## Constitution Check

The change preserves locked runtime/pi, existing user data and credentials. Real HTTP/SQLite and browser evidence are separate. Production deployment requires an exact revision, clean source, image digest, protected backup, pair cutover, rollback readiness and target smoke checks.

## Project Structure

- `backend/app/serialize.py`: UTC time normalization and response.
- `backend/tests/test_acceptance.py`: HTTP/SQLite and stale-evidence regressions.
- `backend/tests/test_acceptance_browser.py`: actual desktop/mobile browser flows.
- `frontend/src/workspace/ContractTab.tsx`, `frontend/src/pages/Workspace.tsx`: functional-check wording and error classification.
- `specs/010-acceptance-check-repair/`: specification, plan, tasks, evidence, and checklist.

## Design

Treat timezone-naive persisted timestamps as UTC, matching model creation semantics. Convert aware values to UTC before comparing and serializing. Classify HTTP 500 as save failure while retaining and labeling any previously saved result. Deploy with the existing schema10 image-only cutover path after independent tests and a protected preflight; do not activate pending publication work.

## Delivery Sequence

1. Record production traceback and tests that fail before the UTC correction.
2. Implement normalization and UI wording; run focused API and real-browser tests.
3. Build exact image from committed source, run protected preflight, cut over and verify the target check and rollback readiness.
