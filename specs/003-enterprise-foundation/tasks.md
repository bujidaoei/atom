# Tasks: Atom enterprise foundation — research stage

Input: spec.md, plan.md, research.md. Status: research-stage decomposition only. Implementation phases below contain design/test preparation tasks, not permission to skip Phase 0. Final code tasks require completed contracts. [x] means this narrow research artifact exists and was reviewed, never that the enterprise capability works.

## Phase 1: Setup
- [x] T001 Read constitution and preserve baseline changes; record scope in specs/003-enterprise-foundation/evidence.md.
- [x] T002 Run Spec Kit feature setup and produce draft specs/003-enterprise-foundation/spec.md with testable stories and assumptions.
- [x] T003 [P] Research seven commercial products using official sources in docs/research/2026-09-30-commercial-products.md.
- [x] T004 [P] Audit current trust and reliability boundaries with source references in docs/research/2026-09-30-architecture-audit.md.
- [ ] T005 Complete Atoms observed flow and register untested branches in specs/003-enterprise-foundation/research.md; generation waits for credit allowance.
- [x] T006 Add dated official incident evidence and distinguish support limitations from incidents in specs/003-enterprise-foundation/research.md (bounded initial sample, not exhaustive vendor history).

## Phase 2: Foundational design
- [ ] T007 Validate user/deployment assumptions and resource targets in specs/003-enterprise-foundation/spec.md.
- [ ] T008 Finalize organization scopes, revision/evidence entities, execution ownership and migration invariants in specs/003-enterprise-foundation/data-model.md; revision 1 drafted, infrastructure validation pending.
- [ ] T009 Define API/error/idempotency and event contracts in specs/003-enterprise-foundation/contracts/ after research gate passes.

## Phase 3: US1 — execution boundary
Goal: genuine isolation and provider credential binding. Independent test: hostile generated content and synthetic-secret destination tests.
- [x] T028 [US1] Validate live tmpfs snapshot export, stop/restart data loss and verified restore with the actual 006 component in scripts/research/probe_snapshot_lifecycle.py; exact bytes/revision restored, cleanup confirmed. Evidence and contract updated; arbitrary-writer quiescence and broker integration remain untested.
- [x] T025 [US1] Validate candidate limits in contracts/isolation.md using scripts/research/probe_container_limits.py; real memory/PID/disk/network/readonly tests passed. CPU load, lifecycle and product/file-tool integration remain untested; SEC-05 remains open.
- [x] T010 [US1] Document threat model and role/endpoint/egress matrix in specs/003-enterprise-foundation/contracts/security.md (design only, enforcement unimplemented).
- [x] T011 [US1] Design isolated reproductions for provider fallback, preview origin and worker access in specs/003-enterprise-foundation/quickstart.md; specify failure expectations before implementation (design only, tests not passed).
- [x] T020 [US1] Reproduce provider credential fallback against an ephemeral loopback capture server using scripts/research/probe_provider_binding.py; retained VULNERABLE result in specs/003-enterprise-foundation/evidence.md. Reproduction complete; security acceptance FAILS.

## Phase 4: US2 — durable execution
Goal: explainable recovery and bounded cost. Independent test: duplicate delivery, process loss and concurrent reservations.
- [x] T012 [US2] Draft lease/fencing, cancellation, event resync, uncertain outcome and cost settlement contracts in specs/003-enterprise-foundation/contracts/execution.md; design revision 1 only, implementation and scenario acceptance remain open.
- [ ] T013 [US2] Define real two-worker and budget fault scenarios in specs/003-enterprise-foundation/quickstart.md.

## Phase 5: US3 — evidence and release
Goal: same-revision verified delivery. Independent test: forged/stale evidence rejected, old release survives failed promotion.
- [x] T014 [US3] Draft trusted runner, evidence invalidation, artifact promotion and data recovery contracts in specs/003-enterprise-foundation/contracts/delivery.md; design revision 1 only, implementation and scenario acceptance remain open.
- [ ] T015 [US3] Define clean-room build, browser and failure/recovery acceptance in specs/003-enterprise-foundation/quickstart.md.

## Phase 6: US4 — collaboration and portability
Goal: controlled enterprise repository integration. Independent test: role matrix and conflicting repository edits.
- [x] T016 [US4] Draft grants, existing-repo onboarding, conflict handling and export guarantees in specs/003-enterprise-foundation/contracts/collaboration.md; proposed design only, independent CO-01…07 tests unexecuted.

## Final phase: readiness and delivery
- [x] T029 [US1] Reproduce and fix post-acquisition runtime cleanup gaps in specs/007-sandbox-lifecycle/tasks.md; real Pi/file-tool regression and lock verification passed. Adapter release is not broker termination acceptance.
- [x] T026 [US1] Implement and locally verify snapshot component specs/006-sandbox-snapshots/tasks.md. No runtime call site exists yet; this closes only the transfer foundation, not SEC-05.
- [ ] T027 [US1] Complete broker grant/lifecycle and snapshot/file-tool integration under specs/008-sandbox-broker/tasks.md, with real cancel/crash/quiesce/export and fenced revision tests. Child T001…T005 complete within documented component boundaries (design, grant, registry, control HTTP, actual fixed-profile driver); in-flight reconciliation/runtime/snapshot/workspace migration remain open.
- [x] T024 [US1] Implement and locally verify specs/005-configuration-guards/tasks.md; no missing-token authorization or signing-secret fallback. Commit 050faba and scoped test evidence recorded; parent production delivery remains T019.
- [ ] T017 Run Spec Kit cross-artifact analysis and replace staged tasks with concrete implementation/debug/test/acceptance tasks in specs/003-enterprise-foundation/tasks.md.
- [ ] T018 Implement and validate accepted increments with evidence in specs/003-enterprise-foundation/evidence.md; this umbrella task must be split before coding and cannot close by prose alone.
- [ ] T019 Deliver verified revision to the requested GitHub repository and document backup/deploy/rollback/live acceptance in specs/003-enterprise-foundation/deployment.md.
- [x] T021 [US1] Complete bounded local credential-binding increment specs/004-provider-binding/tasks.md (implementation, automated checks, local connection browser acceptance and diff review passed). Production delivery stays T019; this addresses part of FR-002 and does not close egress/encryption/organization policy tasks.

## Dependencies and strategy
- [x] T023 [US1] Reproduce local sandbox environment/host-file boundary using only temporary synthetic canaries in runtime/scripts/probe-local-isolation.ts. Windows and Linux confirmed NO_OS_ISOLATION; SEC-05 remains failed/unaccepted. Current agent tool exploitability not tested.
- [x] T022 [US2] Run bounded isolated PostgreSQL claim/fencing experiment scripts/research/probe_queue_claims.py and record exact image, results and limits. Database primitive evidence does not close T013 or product worker acceptance.

T001→T002; T003/T004 can run independently. T003…T007 inform T008/T009. Story design T010…T016 follows foundational contracts; tests remain independent per story. T017 is required before T018 is split and implemented. T019 requires real release gates, backup and rollback evidence. Research UI/document work can continue while credit allowance is pending. No task may be marked accepted solely because a file exists, the agent said done, or fake data rendered.

T027 continuation: child 008 durable operation receipts and real write/retry/crash/revoke component tests pass; HTTP/Pi integration and snapshot-seeded ready lifecycle remain open. Full backend evidence is recorded in child evidence.md; enterprise release is not accepted.

T027 continuation: child 008 can now seed actual provisioning workers from verified input snapshots and commit ready, with eleven real-container cases. HTTP/runtime integration and output checkpoint registration remain unimplemented; T027 stays open.

T027 continuation: child 008 authenticated seed/file HTTP is implemented and tested against real containers and loopback transport. Runtime adapter, output registration and enterprise acceptance remain open; no production enablement is claimed.

T027 continuation: child 008 T007 file-port migration now has actual Pi → Node HTTP adapter → broker → Docker evidence and is complete as a component. Production control-plane orchestration/selection, checkpoint registration and enterprise acceptance remain open; T027 stays unchecked.

T027 continuation: child 008 T009 can now export/verify real quiesced workers; it deliberately leaves state quiescing and checkpoint_revision unset. Durable artifact storage, control-plane revision/attempt-fence migration and registration remain required, so T009/T027 remain open.

T027 continuation: child 008 adds real immutable artifact persistence and verified process/container recovery. Project/run/workspace ownership migration and fenced revision-head registration are specified but not implemented; T009/T010/T027 stay open. Original application tests are preserved and final complete regression passed.

T027 continuation: child 008 now implements offline API schema migration with verified backups and real SQLite/Linux crash/restore tests. Revision registration, application adoption and live migration acceptance remain open; no production database was changed and T010/T027 stay unchecked.

T027 continuation: child 008 now has a trusted control-plane revision ledger with scoped ownership, generation/base checks, atomic head/receipt/outbox and separate termination observations. Real Linux integration connects worker export to stored artifacts and registered output before confirmed release. Production orchestration, endpoints, outbox delivery, legacy statuses and preview adoption remain open; T009/T010/T027 remain unchecked. Official Replit recovery-scope research was refined without implying complete-environment recovery from a file checkpoint.

T027 continuation: broker checkpoint acknowledgement is now explicit and idempotent, separate from generic state progression and worker release. Real registered-output integration covers both acknowledgement and cancellation after API commit. Runtime/HTTP coordinator wiring, preview/outbox and complete enterprise acceptance remain open; T009/T010/T027 are unchanged as incomplete.

T027 continuation: child 008 adds authenticated administrative checkpoint HTTP export/confirmation and bounded response delivery. Runtime grant alone is rejected; revocation remains available during a slow export. API-database registration still belongs to the trusted control plane and has not been wired into production runtime completion. T008/T009/T010/T027 stay open.

T027 continuation: child 008 now has a trusted Python broker transport with real socket protocol tests and actual Linux registration integration over Uvicorn. The latter consumes real persisted receipts. Production execution reservation before provisioning and immutable binding of the returned broker ID remain explicitly required; the existing test harness is not production coordinator acceptance. T008/T009/T010/T027 stay open.

T027 continuation: child 008 replaces post-provision allocation with durable reserve/reload/bind. Real Linux/HTTP integration now persists intent before target-worker creation, recovers identical grant identity after process loss, binds before seed and denies delayed creation after pre-admission cancellation. The separate test ledger container is infrastructure setup. Production coordinator/recovery scheduling, own-runtime server selection and complete acceptance remain open; T008/T009/T010/T027 stay unchecked.

T027 continuation: child 008 now exposes owner-scoped cleanup observations separately from execution authority; cancellation returns its committed recovery identity. Real SQLite and Linux/HTTP tests verify restart and receipt preservation. Production coordinator, runtime server selection and release acceptance remain open.

T027 continuation: child 008 now has an actual cancellation coordinator connecting API intent to broker revocation and confirmed closure, with 41 affected tests passing including real Docker/HTTP and transport fault cases. Production provisioning/completion coordination, scheduled reconciliation, runtime adoption and enterprise acceptance remain open.

T027 continuation: child 008 now prepares actual sandbox leases from reserved intent and immutable stored inputs; real Linux coordinator/store/database and HTTP broker integration passes. Runtime server adoption, successful completion, durable scheduling/ownership and enterprise release remain open.

T027 continuation: child 008 completion coordination now connects actual export, immutable storage, fenced registration, checkpoint acknowledgement and verified worker release; receipt/acknowledgement recovery and storage failure have real Linux/HTTP scenarios. Runtime completion hooks, durable scheduling/ownership, application adoption and enterprise acceptance remain open.

T027 continuation: child 008 now persists terminal decisions before release and recovers real process loss before/after container revocation. Pending decisions are not completion; cancellation remains authoritative until confirmed closure. Production scheduling, runtime lease/completion integration and enterprise acceptance remain open.

T027 continuation: child 008 ready leases now contain distinct sandbox and execution-completion capabilities, explicitly issued with purpose separation and tested against the real broker. Runtime/API completion boundary and production adoption remain open.

T027 continuation: child 008 now exposes a tested execution-only completion/cancellation HTTP component with independent capability verification and durable binding checks. Real Linux store/ledger/two-service HTTP flows pass. Main API/Node integration and release acceptance remain open.

T027 continuation: child 008 now has verified Node completion transport and actual Node-to-Linux API/store/database/broker evidence. Node server/lifecycle adoption, workspace identity, production mounting and enterprise release remain open.

T027 continuation: child 008 has tested outer Node execution lifecycle ownership across recovery and checkpoint-before-release, including actual Linux/Docker completion. Production runtime/server adoption remains open.

T027 continuation: actual ProductAgentRuntime now supports trusted external sandbox ownership across recovery, validated with real Pi sessions/local file IO and synthetic model protocol. Production server wiring and enterprise acceptance remain open.

T027 continuation: child 008 production-mode Node server now uses validated broker leases and checkpoint-before-release lifecycle. Real server/Pi/Docker/Linux registration evidence passed; API orchestrator lease delivery, production mounting and enterprise release remain open.

T027 continuation: API runtime transport can now deliver prepared leases and reject unverified terminal receipts using the ledger. Main orchestrator lease creation/adoption and positive whole-API acceptance remain open.

T027 continuation: child 008 now resolves/creates owner-scoped identities for post-migration projects and heats, with concurrent SQLite verification. File import, application wiring and enterprise acceptance remain open.

T027 continuation: child 008 now implements trusted offline real-directory import before revision bootstrap. Application integration, production writer fencing/cutover and enterprise acceptance remain open.

T027 continuation: child 008 now provides bounded startup attempt scanning and confirmed broker cleanup, including durable success decision recovery after process loss. Main lifespan, exclusive ownership, legacy status adoption and enterprise release remain open.

T027 continuation: child 008 main API now owns broker configuration/resources, Linux process lease, startup/shutdown reconciliation, scoped execution routes and broker readiness. Unleased calls are refused. Scheduling/lease delivery, durable legacy status/preview adoption and enterprise release remain open.

T027 continuation: child 008 adds committed revision read views so validation/preview integration can stop using stale legacy files. Real owner-scope and Linux extraction/cleanup evidence passes; automatic scheduling and actual preview adoption remain open.

T027 continuation: child 008 broker preview and file-read endpoints now serve actual committed artifacts with revision identity and owner checks; real Linux FastAPI route evidence passes. Scheduling, file-list/publication/race adoption, browser isolation/pinning and enterprise acceptance remain open.

T027 continuation: child 008 project/race API catalogues now use verified committed manifests and version identity instead of stale host files or persisted heat counts. Orchestrator event statistics, adoption/publication, lease dispatch and enterprise acceptance remain open.

T027 continuation: child 008 main orchestrator now creates and delivers broker leases and validates committed output; real consecutive build/revise preserves prior artifacts, invalid HTML output fails the Run and delivery disconnect triggers confirmed cleanup. Publication/adoption, revision-bound acceptance, active-model cancellation/deadline, ongoing recovery/outbox and enterprise release remain open.

T027 continuation: child 008 verified active-model runtime cancel/deadline with actual start_build, preserving old committed content and correct Run/project interruption status. API-level cancellation races, continuous recovery, publication/adoption and enterprise release remain open.

T027 continuation: post-registration timeout now rejects late runtime success while retaining the committed artifact receipt. Real delayed-response coverage is recorded in feature 008 evidence; enterprise acceptance remains open.

T027 continuation: cancellation cleanup now survives cancellation of API request waiters; real authenticated ASGI fault tests cover initiating/duplicate callers and shutdown, using a scripted runtime cleanup barrier. Real TCP/broker cancellation acceptance remains open.

T027 continuation: actual release/acceptance authority audit and refreshed official product research are recorded in feature 008 contracts/revision-release.md. Its T014 design audit is complete; T015–T019 migration, implementation and acceptance remain open.

T027 / feature008 T015 continuation: baseline/v1 backup prerequisite now preserves exact version under writer exclusion with real WAL/restore and Linux tests. Release schema upgrade remains unimplemented and unchecked.

T027 / feature008 T015: explicit offline v2 verification/release schema and migration component implemented and fault-tested; runtime remains v1-only. Adoption/full verifier identity/application cutover and enterprise release remain open.

T027 / feature008 T016: canonical contract and complete report content validation now tested; trusted execution, persistence and release authorization remain open.

T027 / feature008 T016: immutable verification-intent reservation and exact replay now pass real SQLite concurrency/scope/drift tests. Verifier execution, result registration and release integration remain unfinished.

T027 / feature008 T016: transactional captured-contract report registration and crash/replay tests pass; trusted verifier execution and actual publication integration remain unfinished.

T027 / feature008 T016: verification cancellation/timeout ledger and bounded expiry inventory now tested, including simultaneous report/cancel. Browser lifecycle and automatic reconciliation remain unimplemented; no enterprise completion claim.

T027 / feature008 T016: atomic release metadata/pointer/receipt and current-evidence checks now pass real SQLite concurrency/rollback tests. This does not expose publication or complete verifier/artifact serving/enterprise rollout.

T027 / feature008 T016: fenced unpublish metadata/replay and publish competition pass real SQLite tests. Actual page/asset visibility enforcement and enterprise rollout remain open.

T027 / feature008 T017: pinned publication metadata now honors current live state and both audience scopes. Database authorization tests pass; real HTTP/artifact/browser isolation and release acceptance remain open.

T027 / feature008 T017: actual immutable release bytes and private cleanup now pass Linux integration, including corrupt storage and unpublish during read. HTTP/browser release acceptance remains open.

T027 / feature008 T017: release-view capacity and post-extraction revocation now pass Linux tests. Real publication HTTP/browser serving remains open.

T027 / feature008 T017/T018: audited browser origin assumptions and documented pinned content hosting/private access/verifier architecture against MDN semantics. No browser security or deployment gate closed.

T027 / feature008 T015/T017: immutable content binding v3 migration and crash/restore component tests pass. Host routing, private capabilities and real browser isolation remain open.

T027 / feature008 T017: immutable content binding allocation/resolution and v3 internal ledger compatibility now pass SQLite tests. Main runtime startup and live routing are unchanged; browser/deployment gates remain open.
