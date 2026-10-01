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


Governance sequencing refinement: persistent destination obligations and administrative generation/receipts precede audit retention. Plan archive verification and isolated restore before authorizing any pruning. Extend release recovery evidence with separately assessed code/schema/data/external-effect/audit coverage. Official research refresh and current-schema configuration-change probes are recorded under008; new-schema rollout and recovery UI remain pending.


008 T033 progress (2026-10-01): bounded exact8 read-only retention planner and operator CLI implemented,59 planner/authority/migration checks pass; details in ../008-sandbox-broker/evidence.md and contracts/audit-governance.md. Context/generation fencing includes active holds and all relevant registered destinations; output explicitly grants no deletion authority and has no archive validation. Archive/independent restore/runtime8 compatibility/production rollout remain open. This is a component increment, not enterprise acceptance.


008 T033 archive format/recovery-core increment:60 codec/planner checks pass, including actual independent subprocess recovery of full business-generated event dictionaries. Strict bounded canonical format binds captured context/plan metadata and requires an externally supplied archive digest. Durable storage, protected manifest authority, persisted recovery receipts and enterprise rollout remain open. See ../008-sandbox-broker/evidence.md; T033/T034 are not accepted.


008 T033 local storage increment:9 actual Linux filesystem/process cases and1 independent-volume writer-removal/read-container test pass for private no-overwrite audit archives. Protected manifest authority, persisted recovery receipts and service integration remain open; local durability is not legal/cloud immutability or production acceptance. Details: ../008-sandbox-broker/evidence.md. T033/T034 remain unchecked.


008 T033 offline schema9 increment: immutable archive manifests and separate recovery receipts added with74 migration/constraint/recovery tests passing. Protected ledger service integration and runtime9 compatibility remain open; metadata constraints do not prove archive IO or recovery. No serving upgrade or deletion authority. Details in ../008-sandbox-broker/evidence.md; T033/T034 remain unchecked.


008 T033 service increment: actual Linux archive publication/readback, source/context revalidation and immutable9 manifest/recovery registration connected.111 tests pass including8 real Linux integration scenarios and retention8/9 authority regression. Operator workflow/configuration and ordinary runtime9 acceptance remain open; no pruning/deployment. Details: ../008-sandbox-broker/evidence.md; T033/T034 stay unchecked.


008 T033 operator workflow: explicit archive/inspect/recover CLI and source-fenced continuation implemented;11 actual Linux integration cases pass, including102 real business events over100+2 pages and hold-after-first-page rejection. See ../008-sandbox-broker/evidence.md. Ordinary runtime9 and enterprise production acceptance remain open; T033/T034 unchecked.


008 schema9 compatibility increment:377 business/governance/main-TLS,64 revision9 and11 actual Linux archive tests pass. Ordinary consumer exact allowlists now include9; new destination/archive race uses real governance commands. Full runtime/browser/production9 acceptance and T033/T034 remain open. Detailed evidence: ../008-sandbox-broker/evidence.md.


008 schema9 runtime/browser evidence:6 actual main/own-runtime/broker cases and Chromium private-content login/revocation flow pass; Pi1905 locked files verified. This narrows previous compatibility gaps but does not prove live model, trusted verifier or production acceptance. T033/T034 remain open. See ../008-sandbox-broker/evidence.md.


008 T033 acceptance audit found and reproduced a recovery authority gap: in-process restore still has source database write access. Existing byte-recovery receipts are not isolated verification. Added unchecked T035 for fixed broker-owned recovery execution and versioned evidence before T033 acceptance; official sources and actual Linux negative evidence are in ../008-sandbox-broker/contracts/audit-governance.md and evidence.md. Enterprise acceptance remains open.


008 T035 worker foundation: fresh fixed broker-owned recovery execution and confirmed cleanup implemented;98 tests pass including4 actual isolated-container success/failure cases. Administrative transport and versioned receipt integration remain open; current CLI still has the documented in-process authority gap. T035/T033/T034 remain unchecked. Details: ../008-sandbox-broker/evidence.md.


008 T035 admin recovery endpoint implemented with authentication, bounded intake/send and cancellation-owned cleanup.24 ASGI/actual-Docker HTTP boundary tests pass. Client and versioned receipt integration remain open; current archive CLI is not yet isolated. See ../008-sandbox-broker/evidence.md.


008 T035 bounded client:42 client/transport checks pass including actual socket broker plus isolated Docker restore and strict provenance/full-payload rejection tests. No grant-signing key required by recovery client. Versioned receipt/owner wiring still open; T035/T033/T034 unchecked. See ../008-sandbox-broker/evidence.md.


T035 abrupt broker-death evidence (2026-10-01): real child processes exit with os._exit(73) after provisioning before restore, after full restore before cleanup, and after actual container removal before durable termination confirmation. Fresh Lifecycle startup reopens the same registry/lease, reconciles each interrupted attempt to terminated before readiness, and leaves no owned containers. A subsequent explicit call performs a fresh full-field restore with a distinct attempt; interrupted calls produce no successful return. Seven actual-container tests pass (40.482s, zero failures/errors/skips), including existing source/mount/socket denial and exit/output/timeout cases. This closes the previously untested internal recovery crash/restart boundary only. Versioned source receipts and archive owner/CLI integration remain open; schema9 historical receipts are unchanged. T035/T033/T034 remain unchecked.


T035 distinct receipt schema foundation (2026-10-01): explicit offline schema10 adds security_audit_isolated_recoveries with protocol fixed to audit-recovery-v2, pinned image, policy digest, verifier/attempt identity, exact archive/payload digests/count, complete canonical response digest and verification time. Archive relationship/time constraints and immutable update/delete/primary-key/alternate verifier-attempt replacement guards apply. Historical schema9 receipts remain untouched and are never promoted; migration creates no isolated evidence.62 migration/constraint/backup tests pass (9.642s, no failures/errors/skips), including sources0..9, full backup restoration, actual pre/post-commit process death, late rollback, CLI preservation and schema10 receipt backup. Frozen migrations1..9 are unchanged. Owner/CLI issuance and ordinary serving compatibility with10 remain unimplemented; do not migrate serving/production databases to10. T035/T033/T034 remain unchecked.
