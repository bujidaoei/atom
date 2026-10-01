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

T027 / feature008 T017: strict content Host codec now tested; real DNS/TLS/ingress, serving and browser isolation remain open.

Feature008 T017 progress: real Linux artifact-backed public content ASGI requests and related regressions pass. Component is not deployed or mounted in production. Private access, browser/transport isolation, trusted verification and enterprise release gates remain open; T027 remains unchecked.

Feature008 T017 evidence extended: two distinct real snapshot versions remain consistent through intervening release promotion; conditional/Range/HEAD requests obey current privacy. Linux ASGI coverage only, with explicit fixture lineage/reports. Enterprise T027 and browser/production gates remain open.

Feature008 T017 progress: bounded content response admission/send lifetime and cancelled-read ownership now pass Linux real-artifact ASGI fault injection plus configuration/host/repository regressions (57 tests). Real network limits, process shutdown, browser/private access and trusted verification remain unaccepted; T027 stays open.

Feature008 T017 progress: bounded truthful ASGI drain and actual Linux Uvicorn TCP serving/startup/shutdown verified (21 targeted tests). Cancelled callers do not erase active IO ownership, and failed drain does not reopen admission. Public TLS/browser/private access/verifier/supervisor deployment gates remain unaccepted; T027 stays open.

Feature008 T017 evidence increment: Chromium local HTTPS attack fixtures validate actual production response headers with network/worker positive controls and console/sibling storage isolation. End-to-end artifact/browser/private-access/verifier/public-TLS acceptance remains open; enterprise T027 remains unchecked.

Feature008 T017 progress: stable public sharing routes now follow current immutable binding with tested denial for private/offline/missing binding and no client-controlled redirect. SQLite, real Linux artifact/ASGI and TCP checks pass (53 tests). Production/private/UI/verifier gates remain open; T027 stays unchecked.

Feature008 T017 progress: real stored Linux artifact page reaches Chromium with eight CSS/eight JS assets. This exposed and fixed an overly restrictive default response capacity; default is now eight with independent snapshot limits retained. Browser composition, policy regression and 21 lifecycle/capacity checks pass. Enterprise load/private/verifier/production gates remain open; T027 stays unchecked.

Feature008 T016/T017 progress: new v3 release and fixed content address now commit atomically, eliminating the share-readiness gap. Collision/late-failure rollback, concurrent publishers and replay are tested; Linux serving and actual Chromium artifact composition pass. Remaining enterprise/verifier/private/deployment gates are unchanged; T027 stays open.

Feature008 private-access design now identifies durable console-session/logout and browser-bound handoff prerequisites. Primary-source research and source audit are recorded in contracts/private-content-access.md; T020–T025 decompose implementation and composed browser/revocation gates. No private feature implemented or accepted; T027 remains unchecked.

Feature008 T020 offline access schema/migration completed with real SQLite constraints/backups/rollback and Linux forced-exit recovery (56 tests). Source-session issuance/revocation integration, private exchange/serving and browser gates remain T021–T025; enterprise T027 stays open.

Feature008 private-access prerequisite: persisted console-session repository lifecycle and concurrency/failure behavior now pass 45 actual SQLite/schema tests. Authentication/signature/HTTP integration and private credential paths remain unfinished under T021/T022; T027 remains open.

Feature008 T021 progress: hash-only browser-bound capability repository and atomic single-use exchange pass actual SQLite concurrency/failure/process-exit tests (64 combined tests). HTTP authentication/cookies, rate/retention, browser composition and v4 serving remain incomplete; enterprise T027 stays open.

Feature008 T022 progress: actual signed credentials now bind to durable session scope/lifetime/revocation with 71 crypto/SQLite/access regression tests passing. Legacy login/cookies remain unchanged; controlled auth cutover, private HTTP/browser and deployment gates are still open. T027 remains unchecked.

Feature008 private-serving progress: dedicated content sessions now authorize real artifact reads and are rechecked through IO; 62 tests include actual Linux revoke-during-read/extraction denial. v4 internal ledgers are supported, but main runtime/auth migration, cookie exchange and browser/private deployment gates remain open. T027 stays unchecked.

T027 continuation (008/T023): root authentication namespace now rejects conflicting verified content manifests and avoids SPA fallback. 14 targeted tests and real Chromium conflicting/normal artifact runs pass. Publication preflight and private exchange/browser acceptance remain unfinished; no enterprise task closure.

T027 continuation (008/T016/T023): real content publication preflight now verifies stored artifacts before promotion and rejects stale state after IO. 34 tests and two actual Chromium runs pass, including corrupt/missing artifacts, publication race and offline replay preservation. Main API selection, trusted verifier and private exchange/enterprise deployment remain open.

T027 continuation (008/T023/T025): service-owned HTTP exchange now has strict metadata/body controls and actual Chromium cookie/private-artifact evidence. 56 tests and private/public browser scenarios pass. Bootstrap and console issuance are still fixture prerequisites; complete authentication, embedded access and enterprise deployment remain unfinished.

T027 continuation (008/T023/T025): real HTTP bootstrap now supplies browser nonce and fixed console redirect; 76 tests and actual private/public Chromium paths pass. Console authorization/issuer is still a fixture, so complete authentication, embedded access and deployment remain unfinished.

T027 continuation (008/T022): actual console auth routes now support explicit durable v4 session mode, real password login and revoke-before-clear logout. 88 targeted tests pass. Existing broker v1 compatibility, console handoff issuance, account-wide revoke/audit and production rollout remain unfinished; no enterprise task closure.

T027 continuation (008/T010/T022): v4 runtime compatibility now passes 130 ledger/fault tests and all 12 actual main-app/own-runtime/broker cases across v1/v4, including durable session coexistence. Earlier schema incompatibility resolved; live migration/rollback, console issuer, full browser and enterprise deployment remain unfinished.

T027 continuation (008/T022): real durable console handoff API now enforces scope/origin/body bounds; 104 regressions pass, including login/issue/logout invalidation and cancelled worker ownership. User action UI, composed browser issuer flow and enterprise operational/deployment gates remain open.

T027 continuation (008/T022/T023): authoritative consent scope API supplies stored project/release/currentness with no credential side effects; 72 regressions pass. Confirmation UI and complete browser/enterprise deployment gates remain open.


T027 continuation (008/T022/T023/T025): actual frontend confirmation and real browser login/issuer composition now pass local TLS/artifact checks, alongside 72 backend regressions and three frontend boundary tests. Synthetic verification metadata remains explicitly seeded; independent verification, broader browser/logout UX, enterprise operations and production rollout remain unaccepted.


T027 continuation (008/T022/T025): truthful logout UI now retains identity on failure and supports explicit retry. Composed browser test proves transport failure leaves actual session active and subsequent real logout invalidates existing content cookie. 40 backend regressions/build pass. Boot/refresh uncertainty, wider revocation/operations and production acceptance remain open.


T027 continuation (008/T022/T025): session inspection now distinguishes unavailable from signed-out, preserving the original confirmation link through failed checks and explicit recovery. Actual browser flow and build pass; background/race matrix and enterprise rollout remain unfinished.


T027 continuation (008/T022): issuer operations now participate in main application shutdown, retaining ownership after caller cancellation and reporting drain timeout truthfully. Related 63-test regression covers real ledger operation and actual main lifespan failure propagation. Enterprise operational and deployment acceptance remain open.


T027 continuation (008/T022): issuer response delivery now participates in admission and drain with validated deadlines. 79 targeted tests pass, including real route/database plus injected ASGI send faults; committed-but-undelivered handoff cannot be issued again. Production ingress/recovery and enterprise acceptance remain unfinished.


T027 continuation (008/T022): account-wide revocation now has actual transactional/API implementation with 109 related passing tests. Existing devices and derived content access are invalidated; fresh subsequent login survives old-source replay. UI/audit and production rollout remain unaccepted.


T027 continuation (008/T022/T025): account settings action and two-browser real revocation acceptance now implemented locally. Build and 30 API tests pass; cancel/failure/retry and derived content denial verified. Audit and enterprise production acceptance remain unfinished.


T027 audit refinement: primary-source comparison and local code inspection now define 008/contracts/security-audit.md and open child T026-T030. Proposed distinction is durable security transitions versus telemetry/denial observations, correlated to immutable release evidence without storing code/credentials. No existing logging or contract document is counted as completed audit capability.


T027/008-T026 increment: offline audit v5 schema foundation implemented and migration/constraint tests executed. Audit writers, all runtime consumer compatibility and enterprise export/retention remain open. No live database migration or audit feature closure.


T027/008-T026-T027 increment: console-session security transitions now persist actual audit events atomically on5, including real password API evidence. Content/publication auditing, all runtime consumers and enterprise audit acceptance remain unfinished.


T027/008-T027 increment: private credential transitions now carry actual transactional revision/release audit provenance; 54 scoped tests pass. Full publication audit, runtime compatibility, observation/export and enterprise acceptance remain unfinished.


T027/008-T027 increment: publication and unpublication now carry actual v5 audit transitions atomically with release state; 54 ledger/audit regressions pass. Main serving/runtime5, observation/export/retention and full enterprise rollout remain unfinished.

T027/008-T026 component acceptance: audit schema migration and runtime compatibility now pass208 ledger tests,18 actual main/Node/broker cases across1/4/5 and v5 real private browser flow with exact persisted audit counts. ChildT026 closed for its bounded schema/compatibility scope. ParentT027 and childT027-T030 remain open for remaining audit/enterprise obligations and production rollout.


T027/008-T027 component accepted: transactional audit emission for all seven committed security transitions has rollback/replay/concurrency and real subprocess before/after-commit recovery evidence. Current34 tests pass. Parent enterpriseT027 remains open; audit denial observations, read/export/retention and production operations are not covered by this closure.


T027/008-T029 increment: audit read foundation implemented with actual scope/source checks and snapshot paging; 28 tests pass. No external audit API/UI, export or production acceptance yet.


T027/008-T029 increment: mounted actual signed-cookie audit read API, strict current scope and bounded independent read/delivery ownership. HTTP/auth/storage/fault/lifespan regression evidence recorded in008. UI, enterprise role model, export/retention and production readiness remain open.


T027/008-T029 increment: durable audit delivery-state operations are implemented and tested with real ledger rows, concurrency and8 subprocess commit-boundary crashes. No network exporter is enabled; destination security, worker lifecycle, actual remote acknowledgement and retention remain open.


T027/008-T029 increment: operator destination policy and verified public-IP-pinned TLS primitive implemented after official OWASP/Python research.77 targeted checks include real TLS host/trust/cancel/stall/failover and delivery-state regression. Actual event sender, destination management, lifecycle and production egress acceptance remain open.


T027/008-T029 increment: real HTTPS audit batch transport now validates explicit matching receiver ack, with local TLS/independent receiver SQLite dedup and lost-ack evidence.101 relevant regressions pass. Automatic lifecycle/configuration/remote operations and audit viewer/retention remain open.
