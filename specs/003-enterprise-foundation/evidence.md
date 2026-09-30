# Evidence and progress

2026-09-30 — enterprise research baseline.

## Completed observations
- Read constitution, active 002 plan/tasks and current source boundary files.
- Created feature branch through Spec Kit git extension; normalized branch to `codex/003-enterprise-foundation`.
- Browser inspected authenticated Atoms project list, dashboard, mode selector, workspace/account settings entry.
- Read linked Atoms official flow documentation and compiled seven-product official comparison.
- Independent static audit produced 14 prioritized findings; no exploit or production changes performed.

## Not completed
- Atoms generation/iteration/recovery/publishing hands-on: pending explicit credit allowance.
- End-to-end enterprise design contracts and implementation task decomposition.
- Business code implementation, security reproductions, real model tests, load/fault/restore tests.
- GitHub delivery and server deployment of enterprise changes.
- 99.9% availability or any enterprise acceptance criteria.

## Workspace preservation
Pre-existing modification: `backend/app/routers/__init__.py`. Excluded from this feature's changes and any automatic commit. `runtime/pi` must remain unchanged. Research artifacts omit account email and secret values.

## Change log
- Initial draft sets evidence-backed delivery as design hypothesis and prioritizes trust boundaries. Proposed numeric acceptance goals are explicitly unmeasured and require resource validation.

## Local verification
- `git diff --check`: no whitespace errors; existing CRLF normalization warnings noted.
- First Pi verifier invocation from repository root failed because it expects runtime as working directory (`atom/pi` missing). This was an invocation-path failure, not evidence of modified Pi; rerun from runtime required.
- Corrected run, `node scripts/verify-pi-source.mjs` with working directory `runtime`: passed, 1905 files, upstream `f07218c4d4bbc12bef056a7058c3dd49dfe41abe`.
- Browser follow-up observed member management, 11 connector cards and Public default project visibility; no invitations, connector grants, settings edits, paid generation or publication performed.

## Continuation — source-backed design and SEC-01 reproduction

Previous goal turn classification: progress (new research/spec artifacts and observed browser evidence). Current continuation re-read actual worktree, constitution, plan/tasks and source; original user modification remains untouched.

New artifacts: `contracts/security.md`, proposed `data-model.md`, and `quickstart.md`. They define enforceable boundaries, relational invariants, failure cases and evidence requirements, but do not establish implemented functionality. Plan sequencing updated to permit independent security design while competitor credit authorization is unresolved; complete research remains required for overall delivery.

Command: `backend/.venv/Scripts/python.exe scripts/research/probe_provider_binding.py` from repository root.
Result: exit 1, `SEC-01-model-discovery`, `VULNERABLE`; one loopback request, synthetic managed key received at user endpoint, no resolver error, zero external model calls. A temporary database and freshly generated test key were used; actual settings/gateway code and HTTP transport executed. No production data or real key inspected. Receiver and temporary database cleaned up. This is intentionally a failing security result, not a passed gate.

Remaining scope: reproduce/repair every provider call path, enforce destination/credential pairing and egress, then test approved connections still work. No business code fix or production deployment was performed in this continuation.

## Subsequent continuation — provider binding implementation
The preceding paragraph describes the prior research turn. Current progress: child feature 004 implements the shared credential binding and real-only catalog behavior; 85 backend tests, frontend build, 4 runtime tests and Pi boundary check passed. The original loopback probe now observed zero requests. Subsequent real Chrome connection UX acceptance passed repair, rejected endpoint-only change, explicit rebind and default reset against isolated services. See ../004-provider-binding/evidence.md for exact scope and commands. Live model acceptance, egress/tenant isolation, remaining enterprise capabilities and final GitHub/production delivery remain open.

## Continuation — durable execution and delivery contracts

Previous turn classified as progress: actual browser evidence changed T004/T007 state. Re-read current files/diffs. Added proposed execution and delivery contracts from inspected command/orchestrator/event/credit/publication code and primary PostgreSQL, SLSA and GitHub guidance. T012/T014 close only their draft-design deliverables; no enterprise capability accepted. Spec FR-004…008/012 scope unchanged.

Local Docker reported Linux engine 29.4.1. Strict read-only SSH attempt to the designated server stopped at unknown ED25519 host identity before authentication; no password transmitted, no remote command executed, no production changes. Server resources and trusted host fingerprint remain unverified. Existing deployment script is not authorized as-is by these checks.

T022 command: `backend/.venv/Scripts/python.exe scripts/research/probe_queue_claims.py --image pgvector/pgvector:pg17`. Exit 0 in 7.07 seconds. Existing local image pinned internally to `sha256:cf134a767f474095eeba57e0117be8e568e011a63f33fbf252f14c9b760f8e6f`; PostgreSQL 17.11 (Debian 17.11-1.pgdg12+2). No image pull, host network/ports/mounts or real credentials. Temporary container and data removed in finally; subsequent container listing empty.

Observed: transaction A held job 1 through a server-observed PgSleep barrier; transaction B returned job 2 while A remained active. Expired-token update affected zero rows; after token increment, stale token affected zero rows and current token affected one. This proves these SQL primitives in the experiment only. It does not test Atom worker integration, migration, crash recovery, external effects, budget concurrency, HA or capacity. PostgreSQL production version remains a decision to validate, not silently selected from the locally available test image.
