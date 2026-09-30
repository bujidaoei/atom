# Implementation Plan: Atom 企业级交付基础

**Branch**: `codex/003-enterprise-foundation` | **Date**: 2026-09-30 | **Spec**: [spec.md](spec.md)
**Status**: Phase 0 research in progress. This is a phased design direction, not an approved final implementation contract.

## Summary
先用实际流程、官方资料和源码审计建立证据，再按安全边界、持久执行、可信交付、企业协作推进。沿用自有 runtime 和锁定 Pi，保留已验证的幂等、终态和恢复能力。

## Technical Context
- Existing: FastAPI/SQLAlchemy/SQLite, React 19, Node 24 runtime adapter; single worker, local file storage and same-host process supervision.
- Target direction: modular control plane; provider connection policy; isolated execution and preview; independently trusted test runner; immutable artifacts and releases.
- PostgreSQL and versioned migrations are candidates for concurrent durable coordination; exact supported version, queue choice and deployment layout require design validation before implementation.
- Tests: backend regression, runtime integration, browser acceptance, synthetic-secret negative tests, fault injection, capacity and restore drills. Historical passes do not prove this feature.
- Platform: local Windows development and Ubuntu deployment. OS isolation must be validated on deployment OS.
- Targets: see SC-001…007; quantitative values are draft acceptance goals, not benchmarks.

## Constitution Check
Research entry passes: no Pi changes, no credentials stored, user modifications preserved, findings clearly marked static vs tested. Implementation/release gate remains CLOSED until Phase 0 questions and executable contracts are resolved. Production requires backup, traceable revision, rollback and live verification.

Scoped exception to sequencing, not to acceptance: source-backed credential binding proceeds as separately specified `004-provider-binding`, with its own complete readiness checklist and regressions. Parent-wide architecture/HA and release gates remain closed. This enables a permanent shared resolver for a demonstrated defect without pretending broader research or enterprise delivery is complete.

The same bounded process applies to `005-configuration-guards`, which closes demonstrated missing-credential startup and runtime authorization fallback. Its own readiness, startup/HTTP tests and migration instructions are mandatory; it does not close origin/CSRF/isolation/HA gates.

`006-sandbox-snapshots` implements the researched immutable-transfer component after local isolation/quota probes. Its explicit component readiness, Linux filesystem tests and malformed-stream evidence permit this foundation independently of paid competitor access. Broker, grant validation, runtime integration, fenced registration and crash cleanup remain open; no production isolation claim follows from a serialization component.

`007-sandbox-lifecycle` closes source-identified post-acquisition cleanup gaps before real containers are introduced. Require reproduction through actual ProductAgentRuntime, exit-path tests and real Pi regression. This is adapter ownership only, not verified container termination or broker acceptance.

`008-sandbox-broker` now decomposes T027 into grant, registry, fixed-profile driver, typed file operations, HTTP adapter, explicit checkpoint registration and migration gates. It remains in progress throughout component implementation; no signed-token unit test or local Docker probe closes real integrated isolation.

## Project Structure
- `backend/app`: control plane and current authorization, provider and orchestration paths.
- `runtime/src`: own runtime adapters; place isolation boundaries here or a dedicated worker adapter without changing `runtime/pi`.
- `frontend/src`: expose accurate state, effective permissions and acceptance evidence using existing design language.
- `deploy`, `scripts`: reproducible environments, migration, smoke and recovery procedures.
- `specs/003-enterprise-foundation`: spec, research, staged plan, research tasks and evidence.
- `docs/research`: source-backed comparative research and architecture baseline.

## Phase 0: Research and design gates
1. Complete Atoms observed flow subject to account/resource access; mark inaccessible branches explicitly.
2. Deepen official product issue/incident evidence and map useful mechanisms to source risks.
3. Define threat model, permission matrix, provider endpoint policy, trust boundaries and release evidence schema.
4. Validate infrastructure and migration choices against actual resources and workload.
5. Draft evidence-supported invariants in `data-model.md`, `contracts/security.md`, `contracts/execution.md`, `contracts/delivery.md` and `quickstart.md` while independent research continues. These are proposed contracts, not implementation acceptance. Final API/execution/delivery/collaboration contracts and code-level tasks require their own resolved research gates; account access for unrelated competitor tests must not prevent source-backed security design.
6. Validate database claim/fencing primitives in a bounded disposable local container with no host ports or real data. This informs technology selection but does not replace actual API/worker, ledger or fault-recovery acceptance. Current local Docker is Linux 29.4.1; production resources remain unknown.

## Phased implementation direction
### Increment A — trust boundaries (US1)
Unified provider credentials/destination policy; production config fail-closed; independent preview origin; sandbox capabilities and secret isolation. Test actual denial, not merely configuration presence. Existing builder's limited tools remain constrained.

Isolation design in contracts/isolation.md replaces the sandbox port via a separate broker and quota-backed per-attempt workspace, with immutable input/output snapshots. Ordinary host binds cannot satisfy disk quotas. Validate candidate limits before committing implementation interfaces; keep current limited file tools, no model-facing shell expansion. Shared-kernel containers alone do not close public multi-tenant isolation.
### Increment B — durable execution (US2)
Versioned storage migrations, atomic command/lease ownership with stale-worker fencing, cross-worker event delivery and resync; cancellation/retry state machine; reserved/settled budget ledger. Never enable multiple API workers before these invariants are proven.
### Increment C — evidence and release (US3)
Independent browser runner, exact-revision evidence and invalidation; immutable artifact manifest; server-enforced release gates; atomic promotion and tested recovery. Keep client feedback distinct from trusted verification.
### Increment D — enterprise workflow (US4)
Organization roles and existing-repository integration; conflict-safe review workflow; policy audit/export; reproducible private deployment. Organization scope must be designed in A, even if full collaboration UI follows later.

## Validation and change management
Every implementation task includes negative cases, failure injection where relevant, exact revision and actual evidence. Spec changes record rationale and affected requirements/tests in evidence.md. Failed/blocked checks remain open. Credentials never appear in research, commands persisted to repo, screenshots committed to repo or logs exported for support.

## Complexity Tracking
No constitution exception requested. Research-dependent architecture choices remain open instead of disguising guesses as final design. Single-server first delivery is a recovery milestone, not proof of high availability.
