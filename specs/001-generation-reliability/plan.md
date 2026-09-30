# Implementation Plan: Reliable generation
Branch: codex/001-generation-reliability | Date: 2026-09-30 | Spec: [spec.md](spec.md)

## Summary
Repair adapter boundaries; orchestration owns durable terminal outcomes. Preserve sessions/files, bound recovery and cleanup, reconcile state, execute input prerequisites.

## Technical Context
Python 3.12+/FastAPI/SQLAlchemy/SQLite; Node 24/TypeScript/Pi; React 19/Vite. Linux production, Windows development. pytest/Node test runner/real Chromium/live model checks. Single worker, 180-second default build budget, two recoveries, bounded cleanup.

## Constitution Check
Initial and post-design: specification/task tracking, immutable Pi, honest evidence, no secrets, rollback and data preservation satisfied by design.

## Design and Structure
backend/app/services: independent asyncio timeout, strict terminal protocol, finally-based run persistence, cancel/startup/race reconciliation. backend/app/events.py: ordered persist-and-deliver. runtime/src: bounded same-session truncation recovery and sandbox cancellation. workspace-tools.ts: explicit environment root with /workspace fallback. frontend/src/workspace: authoritative status reconciliation and typed setup actions using iframe-native setters/events. Existing string status columns require no schema migration. Project detail exposes latest run diagnostics. Acceptance reports must exactly cover contract checks.

## Delivery
Execute tasks.md sequentially with regression tests first. Live calculator/lottery/snake follows deterministic checks. Push tested branch, inspect server, back up database and old image, build before switching, verify health and smoke. Roll back image on failed health; never overwrite data backups.

## Risks
Provider latency can still exhaust budget; report timed_out. Current local shell is not hardened tenant isolation. Acceptance is browser-reported, not server certification. Scale-out remains out of scope.

## Evidence-driven change 2026-09-30
Live tests showed Alex spending the remaining budget constructing fake DOM harnesses after working files were complete. Static builder now exposes only file tools through ProductAgentRuntime.workspaceToolNames. Shell remains available to other runtime consumers, but not the Atom sidecar. Backend performs actual resource/JavaScript syntax validation as a completion gate. This removes unnecessary authority and makes validation deterministic; it does not claim browser acceptance.

Production follow-up: acceptance now waits at most 1.5 seconds for temporarily disabled controls, including each setup action and the final click. Permanently disabled controls still fail. Contract instructions define setup versus final-trigger semantics, reset state between scenarios, and disallow impossible reverse-direction snake checks. Generation instructions require responsive 360px sizing. These improve generation constraints without rewriting failed test results or claiming arbitrary generated apps are certified.
