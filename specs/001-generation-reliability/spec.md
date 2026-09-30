# Specification: Reliable generation and acceptance

Created: 2026-09-30 | Status: Implementation in progress
Input: Repair truncation recovery, 180-second deadline, stale activity, file tools and acceptance prerequisites; test, push and deploy under Spec Kit.

## User Scenarios & Testing

### US1 — Recover generation (P1)
Retain files and resume the same session after truncation up to twice within the original budget. Expose attempts; cancellation never retries. Test transient and exhausted recovery.

### US2 — Trust status (P1)
Cancel and refresh without perpetual activity. Silent and active builds stop at 180 seconds plus at most 10 seconds cleanup. Restart marks orphans interrupted. Partial preview never means success. Test EOF, early cancel, restart, mixed/all-failed races and event order.

### US3 — Reliable file tools (P1)
Write/read/edit/glob/grep share the real workspace. Test nested-file roundtrips, two workspaces, traversal/symlink rejection and shell cancellation.

### US4 — Meaningful acceptance (P1)
Execute ordered input/click/key prerequisites. Invalid setup fails clearly without aborting later checks. Duplicate or missing reports cannot inflate success. Test a real browser required-input form and invalid selectors.

### Edge Cases
Empty stream, missing terminal, no index.html, credits exhausted, cancel before task starts, restart with sidecar alive, empty contract, historical event replay, adoption during generation.

## Requirements
- FR-001: Bounded session recovery, observable attempts and aggregate usage.
- FR-002: Hard elapsed deadline independent of incoming events.
- FR-003: Durable idempotent project/run/race/heat terminal outcomes.
- FR-004: Persisted status controls activity; reconnect reconciles ordered events.
- FR-005: Consistent workspace operations without changing locked Pi.
- FR-006: Validated setup actions and exact acceptance result accounting.
- FR-007: Preserve existing data/contracts; incomplete generation cannot publish.
- FR-008: Regression and live calculator/lottery/snake evidence recorded honestly.

### Key Entities
Project, Run, Race, RaceHeat, Requirement/Check/SetupStep, AcceptanceRun, RunEvent.

## Success Criteria
No running records after timeout/cancel/restart/EOF regressions; at most two recoveries; all file and prerequisite regressions pass. Three real requests evaluated for elapsed time, generation and browser interactions. Production health and smoke verified against released revision; failures remain open.

## Assumptions
Single API worker. 180 seconds is a budget, not a guaranteed model success. Existing auth retained; scale-out and hardened OS isolation are separate infrastructure work. Secrets remain outside tracked files.
