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


T027/008-T029 increment: real audit ledger and HTTPS sender are composed by an owned recurring exporter with tested cancellation/drain semantics and terminal-error stop.56 checks pass, including actual TLS lost-ack scheduled retry/dedup. Main-service enablement/configuration/global supervision, production receiver/egress and retention remain open.


T027/008-T029 increment: operator export settings and real main startup/shutdown integration implemented with max4 destinations/process and all-before-send preflight.113 related regressions pass; main fixture uses injected sender outcome, with realTLS transport evidence kept separate. Production composition, operational visibility, retention and deployment remain open.


T027/008-T029/T030 increment: true main-auth-export-TLS composition now tested without sender outcome substitution; independent receiver persists identical full event payloads through lost ack and rejected-collector/restart recovery, while account revoke remains available.28 focused checks pass. Production/global operations/retention remain open.


Audit main integration regression:18 actual Linux main/own Node/broker execution cases pass across schema1/4/5 (exports disabled in this matrix). Separately28 enabled-export/main/TLS/service checks pass. Pi1905 files match locked SHA. Production combined deployment/observability/retention gates remain open.


T027/008-T029/T030 increment: actual operator backlog inspection now counts unenrolled work and exporter operational logs redact/deduplicate state changes.44 related regressions pass, including CLI subprocess failures and real TLS/main recovery. Durable observability/denial sink/retention/production gates remain open.


T027/008-T029/T030 refinement: refreshed official Atoms/GitHub/GitLab governance evidence and verified removed/new receiver behavior in real SQLite (35 related checks pass). Add008-T031-T034 for persistent obligations/administration/archive/retention in dependency order. Recovery-manifest design refines FR-008; no implementation checkbox or production readiness claim is advanced.


008-T031 partial increment: explicit offline schema6 registry migration preserves historical destination scopes, rejects mixed scope, and adds generation/state and active-scope delivery guards. 99 focused migration/delivery/configuration tests pass. Runtime consumers are not yet compatible with6; do not migrate serving databases. Administration/retention and complete T031-T034 acceptance remain open.


008-T031 partial compatibility increment accepted at component scope:105 business/migration,67 HTTP/delivery,272 revision/publication,18 main-preflight and24 actual Linux main/runtime cases pass (overlap between suites). Pi1905 files verified. Business consumers support exact6 and preserve audit writes; configured exports still reject6. T031-T034 remain unchecked pending registry-aware exporter/administration and complete acceptance; no production upgrade.


008-T031/T032 foundation increment: explicit offline schema7 adds immutable typed destination command receipts without changing v1-v6 definitions/hashes. Trusted operator repository and app.audit_admin implement register/suspend/resume/block/retire with expected generation, exact replay and atomic registry/receipt commit. Retirement rejects every unconfirmed scoped event, including never-enrolled rows.111 focused tests pass. Ordinary business/runtime/export consumers still refuse7; full integration, operational backlog coverage and T031-T034 acceptance remain open. No serving database upgrade authorized by this component evidence.


008-T031/T032 governed delivery increment: delivery repository and standalone exporter now support exact schema7 alongside5 (6 remains unsupported for export). Explicitly registered matching scopes are required; only active destinations enroll/claim, and claims capture generation. In-flight valid leases may still settle after suspend. Permanent failure persists a generation-fenced block receipt; stale failures return superseded and never overwrite newer administration. Restart preserves inactive state until explicit resume.115 focused tests pass. Main/business consumers still lack7 compatibility, registry-wide backlog reporting and full acceptance remain open; do not upgrade serving databases.


008-T031/T032: Current schema7 compatibility (supersedes earlier not-yet-compatible notes): authentication, content capabilities, revision/verification/publication, audit reads and governed export now accept their explicit verified schema7. Main plus actual TLS verifies lost acknowledgement and permanent rejection across restart; explicit operator registration/resume remains required.28 main/TLS/service checks and529 business/HTTP/revision checks pass. Global historical backlog reporting, full browser/production/retention gates remain open; this is not rollout approval.


Schema7 runtime follow-through:30 actual Linux main/own Node/broker cases pass across1/4/5/6/7 with export disabled; separately28 main/TLS and529 consumer tests pass. Source Pi remains locked. Full T031/T032 and enterprise rollout remain open for wider required acceptance and historical operational visibility.


008-T032 operational visibility increment: audit_admin status now reads every registered historical obligation in one exact7 read-only snapshot, independently of process configuration. A bounded keyset detail page includes never-enrolled/pending/leased/delivered/expired counts and timestamps, while registered_drained is checked over the entire registry, not the page. Empty registry is not drained.64 focused tests pass. Scope is explicitly registered_destinations, not all possible unregistered business scopes or proof of active transport; retention/deployment/full-task gates remain open.


008-T031/T032 are accepted at component scope: versioned governance schema and exact consumer compatibility, durable generation-fenced administration and registry-wide obligation inspection. Actual Chromium5/7 private content/auth/revocation checks supplement prior migration/crash/TLS/runtime evidence. This does not close retention, denial observation, trusted verifier, live model or enterprise production acceptance. Parent enterprise task remains open.


008-T033 research increment: official SQLite backup/WAL and S3 version-lock/checksum documentation plus31 actual backup/probe tests establish separate disaster-recovery and scoped archive boundaries. A raw main-file copy can pass exact schema/integrity while missing committed WAL events; checked backup/restore preserves full payloads. Refined policy/hold authority, registry-set fencing, bounded extraction, manifest and independent restore protocol in contracts/audit-governance.md. No archive/pruning capability implemented or accepted.


008-T033 offline foundation increment: explicit schema8 adds typed retention policies, independent legal/operational holds and immutable administrative receipts; v1-v7 migration definitions remain unchanged. Migration creates no default policy or hold and authorizes no deletion.91 migration/constraint/recovery tests pass. Operator repository/CLI, bounded planning, archive/restore and runtime8 compatibility remain unimplemented; T033/T034 stay unchecked. Schema8 is isolated/offline only and must not be selected for serving databases. T031/T032 acceptance continues to refer to schema7 capabilities.


008-T033 authority increment: RetentionRepository and local app.retention_admin now implement explicit create/update policy and place/release independent holds. Expected policy generation fences every mutation; state/hold/typed immutable receipt commit atomically. Exact replay returns the original outcome, changed-payload command reuse fails, no defaults enable retention.78 focused tests pass. Planner/archive/restore and runtime8 compatibility remain open; no serving migration or deletion path. T033/T034 stay unchecked.


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


T035 archive owner isolated receipt integration (2026-10-01): AuditArchiving.recover_isolated reads bounded committed bytes using the immutable ledger digest, validates every manifest anchor, calls the real configured AuditRecoveryClient and only then commits distinct schema10 evidence. The canonical full broker envelope digest is persisted. The write transaction rechecks the exact archive row; same recovery ID requires archive/verifier/image/policy identity and returns existing evidence after store validation without rerunning recovery. No source transaction spans network IO. Source file preparation is read-only in a worker thread; cancellation before successful transport cannot schedule a write, while the bounded final transaction is synchronous and owned. RetentionRepository supports exact8/9/10; archive publication/inspection supports9/10, and legacy recover refuses10. Inspection reports isolated and historical receipt counts separately.99 tests pass (61.849s, zero failures/errors/skips), including six real Linux store/network/broker/worker scenarios and retention8/9/10 plus legacy archive regression; the six scenarios were rerun successfully after adding inspection-count assertions. CLI isolated recovery, receipt commit-crash acceptance and ordinary serving10 compatibility remain open. T035/T033/T034 remain unchecked; no production migration/deletion/deployment.


T035 operator CLI and receipt commit-death acceptance (2026-10-01): archive_admin now exposes recover-isolated with required archive/recovery/verifier IDs, broker origin, expected pinned image and policy digest. It reads the existing ATOM_BROKER_ADMIN_TOKEN environment variable, never a command-line secret, and reports bounded error codes/receipt metadata without raw archive events. Nine actual Linux owner/network/broker/worker scenarios pass (45.189s, no failures/errors/skips), including actual CLI process death immediately before/after its isolated receipt COMMIT. Before-commit death leaves zero receipts and explicit retry performs a second real worker attempt; after-commit death leaves one receipt and retries return identical persisted evidence with one total worker attempt. Missing credentials fail safely; exact replay and distinct historical/isolated inspection counts are verified. Three legacy CLI/multi-page regressions also pass. This supersedes prior CLI-not-connected and receipt-commit-crash-not-tested statements only. Serving10 integration, deployment TLS/configuration and full T035/T033 acceptance remain open; T035/T033/T034 stay unchecked. No production migration, pruning, push or deployment occurred.


Schema10 serving compatibility increment (2026-10-01): access/content/revision/verification/publication/audit consumers now explicitly admit exact schema10 and preserve full schema/journal checking inside owning transactions. Governance and delivery retain existing generation/registry state behavior; ordinary schema8 serving remains unsupported.457 business/audit/crash/governance/export/main-TLS tests pass (117.661s),64 schema10 revision repository tests pass (17.306s), and6 real main/own Node runtime/broker/container scenarios pass on10, all without failures/errors/skips. Runtime covers valid/invalid/disconnected model output, cancellation, deadline and checkpoint deadline, with synthetic model stream and export disabled; main TLS export is separate actual receiver evidence. Pi1905 files verify against f07218c4d4bbc12bef056a7058c3dd49dfe41abe. This supersedes earlier serving10/runtime10-not-integrated statements at these tested scopes only. Browser10, live model/verifier, deployment TLS/configuration and full retention acceptance remain open. T035/T033/T034 remain unchecked; no production database migration, push or deployment.


Schema10 browser acceptance (2026-10-01): actual Chromium145.0.7632.6 completed the existing private-content workflow against Linux backend schema10: password login, consent, private handoff/exchange, artifact assets, logout retry/revocation, session-check recovery and account-wide revocation. Persisted audit counts match release.published1, console.session.created3, console.session.revoked1, console.account_sessions.revoked1, content.handoff.issued2 and content.session.created2. Eight scripts and eight styles load from the stored artifact. Desktop1440x900/mobile390x844 confirmation screenshots were visually inspected without overflow/obscured controls. Frontend TypeScript/Vite build passes; all62 built files exactly match the pre-build assets used in browser acceptance. This supersedes browser10-not-tested only within the exercised workflow. Local disposable TLS bypass and preseeded verifier metadata remain test limitations; live model, independent trusted verification, deployment TLS/backup and full T035/T033/T034 acceptance remain open. No production push/deployment.


T035 scoped acceptance (2026-10-01): completed after requirement-by-requirement inspection of current worker/lifecycle/HTTP/client/owner/CLI/schema10 code and real recorded evidence. The additional actual-worker probe verifies host-only synthetic credentials absent from both helper environment and PID1 environment, actual source/store/socket open denial, and external connection failure with no network route. Seven worker/crash tests pass without failures/errors/skips. The schema10 enterprise recovery path now has positive OS denial evidence; the schema9 authority-gap probe remains deliberately retained as a historical regression demonstrating why old receipts must never authorize isolation-dependent operations. T035 alone is checked complete; T033 overall archive/retention acceptance, T034 pruning, remote deployment PKI/backup and broader enterprise gates remain open. This supersedes earlier T035-open notes, not the whole product objective. No production migration/push/deployment.


T033 schema10 multi-page isolated recovery evidence (2026-10-01): the actual Linux owner/store/network/broker workflow now covers102 real console-session business events archived as100+2 and recovered by two distinct isolated calls. Concatenated recovered dictionaries exactly equal every original typed source row in sequence order. A legal hold inserted between pages prevents second-page publication while preserving the first archive/receipt. Missing and corrupted committed objects prevent isolated receipt issuance.13 actual integration scenarios pass with zero failures/errors/skips, including prior CLI, commit-crash and failure cases. This closes the former multi-page evidence gap between legacy schema9 recovery and current isolated schema10. It does not prove production capacity, off-host recovery or T034 deletion/reader-gap semantics; T033/T034 remain unchecked and T035 remains accepted. No production migration, push or deployment.


T033 cold container recovery increment (2026-10-01): an actual Linux writer publishes a registered audit archive, saves the object through the real private store and creates a verified schema10 SQLite backup on a dedicated test volume. After writer exit/removal is explicitly observed, a fresh reader receives that saved volume read-only and no original source mount. It verifies the independently passed backup digest/version, restores the source ledger to fresh storage, reads the registered object by ledger digest, invokes actual isolated broker recovery and persists/replays a distinct receipt. Recovered event dictionaries match all original typed source fields. Two focused cases (cold recovery and nearby ordinary success) pass in9.329s with no failures/errors/skips. Owned test volume is label-checked and removed. This proves independence from the removed writer process/container, not off-host disaster recovery, physical power-loss durability or production storage capacity. T033/T034 remain open; T035 remains accepted. No production access, migration, push or deployment.


T033 real storage-exhaustion evidence (2026-10-01): actual ENOSPC is now exercised on dedicated container tmpfs filesystems for both archive storage and source SQLite storage, on schemas9 and10. Archive-full failure leaves no committed object/stage or manifest/receipt. Source-full failure after archive publication leaves one safe unregistered object and no manifest/receipt. In both cases the complete source database dump remains unchanged; freeing only the test filler permits a reopened service to publish/register and exactly replay the archive. Five focused cases including ordinary success pass with zero failures/errors/skips. This supplements injected write/fsync failures with genuine kernel/SQLite exhaustion; it does not measure production throughput/reserve or prove host power-loss durability. T033/T034 remain open, T035 accepted; no production access, push or deployment.


T033 component acceptance audit (2026-10-01): the stated task (read-only policy-bound planning, bounded immutable archive/manifest, independent full-payload restore, holds and complete destination obligations) is accepted after inspecting current source and recorded real test outputs. T031/T032 and T035 dependencies are accepted. T033 is now checked at this component scope; this does not enable retention deletion or close production capacity/egress/off-host disaster recovery. Contract acceptance item7 explicitly keeps operational gates separate, and T034 explicitly owns deletion, reader gaps and deployment backup/restore. Earlier blanket T033-open notes are superseded only for its implemented component requirements. T034, T029/T030 and the enterprise goal remain open; all current event/delivery delete guards remain active. No production migration, push or deployment.


T034.1 offline schema11 foundation (2026-10-01): explicit migration adds immutable prune receipts and per-event archived markers, exact archive/isolated-recovery/policy anchoring, bounded count checks, alternate-key replacement guards and archived sequence/event-ID reuse rejection. Persistent event/delivery delete guards require matching markers plus connection-local atom_prune_authorized(command_id,event_id,sequence); absent/false authority fails closed, pending/leased deliveries cannot be removed, and remaining delivery children prevent parent deletion. No maintenance service installs this function in production.55 schema/guard/migration/legacy-schema10 tests pass (9.394s, no failures/errors/skips), including source versions0..10 backup/replay, late rollback, actual pre/post migration-COMMIT death and ordinary connection denial. Frozen migrations1..10 unchanged. Serving and retention/archive owner still reject11. These are synthetic schema constraint tests, not real authorized prune acceptance. T034 and its subtasks remain unchecked pending full owner/reader/race/deployment implementation; T033/T035 remain accepted. No production migration/push/deployment.


T034 bounded owner increment (2026-10-01): AuditPruning implements an explicit local schema11-only maintenance operation for one complete archived chunk. It reads committed bytes by ledger digest, validates every manifest field and the full isolated-response digest against configured verifier/image/policy, then rechecks current policy/context/age/holds/destination obligations and exact typed source rows in one bounded transaction. All delivery rows must be settled and bounded. Exact connection membership permits immutable receipt/marker insertion and child-then-parent deletion; exact counts are asserted and callback authority is cleared in finally before commit. Command replay binds full request/configuration and reports historical outcome without claiming current archive availability.7 actual Linux store/network/broker/worker integration cases pass (27.299s), including successful scope-preserving deletion, replay/conflict, hold/corruption/wrong verifier/missing receipt denial and injected failure after actual SQL deletion rolling back the complete database. Shared repository/schema regression also passes. No CLI or gap-aware reader/UI is implemented; serving remains exact10 and refuses11. T034 and subtasks remain unchecked, T033/T035 remain accepted. No production prune/migration/push/deployment.


T034 CLI/commit-death increment (2026-10-01): app.prune_admin exposes the bounded schema11 owner with every authority and fence argument explicitly required. It emits a durable JSON receipt or stable domain error; it requires no broker credentials because independent recovery is already committed. Ten actual Linux store/broker/worker integration cases pass with no skips/failures/errors, including CLI success/replay/conflict and actual CLI process death immediately before and after prune COMMIT. Pre-commit death leaves the complete database dump unchanged; post-commit death durably preserves exact markers and receipt while removing only the authorized source rows and settled children, and retry returns the original receipt. New ordinary connections remain unable to delete. T034 and all subtasks remain unchecked pending gap-aware readers/UI, remaining races, prune ENOSPC and deployment acceptance. Serving still refuses11; no production migration/prune/push/deployment.


T034 authorized archived-reader increment (2026-10-01): AuditRepository now admits exact11 and reauthorizes the source session and account/project scope in the same read transaction before selecting either live payloads or archived identities. A single sequence-ordered union applies one total page limit, computes the default upper from both tables and preserves continuation across deletion. Archived markers are separate typed records with original identity/scope/class plus command/archive/recovery references and archived_at; they do not claim current object availability or reconstruct deleted payloads. The HTTP response adds an archived array (empty on prior schemas). Real Linux archive/isolated-recovery/prune tests verify mixed and all-archived histories, continuation from a pre-prune cursor, exact identity coverage, scoped references, read-only behavior and foreign/expired/revoked denial. Legacy query/routes/schema guards regress successfully. Only the reader admits11; authentication/serving still reject11, and no audit UI exists yet. T034 and all subtasks remain unchecked pending full API/auth/UI/runtime11, larger-page acceptance, remaining races/ENOSPC and deployment gates. No production migration/prune/push/deployment.


Immediate deployment request (2026-10-01): user prioritizes finishing and viewing the latest code on the existing server. Application revision94bfcd77876e056daff35096df8bd9623926fa86 is pushed to origin/codex/008-sandbox-broker and independently confirmed by git ls-remote. Deployment must preserve existing data/configuration and locked runtime, use a verified SQLite backup before schema changes, and keep unaccepted schema11 pruning disabled. Current source production mode requires broker execution and HTTPS cookies; the historical single-container configuration cannot be assumed compatible. Inventory and provision required private broker/artifact/schema configuration before switching traffic. Live server HTTP /atom/api/health currently returns200 with ok/runtime true; this proves only the existing service. Repeated SSH banner timeouts prevent inventory/backup/cutover, before password authentication; native SSH once reached an authentication rejection in BatchMode, so connectivity is intermittent. No remote service or data was changed. User was asked to check cloud-console SSH/security-group state or provide an alternate connection. Release image build is in progress locally; neither build completion nor remote deployment is claimed. Full enterprise acceptance remains open.


Release preparation result (2026-10-01): clean git archive of94bfcd77876e056daff35096df8bd9623926fa86 builds successfully as atom-release:94bfcd7 with VITE_BASE=/atom/. Final image uses full revision label and excludes the unrelated local routers/__init__.py edit. Build verifies all1905 SHA-locked Pi files and imports the Pi gateway bundle; frontend TypeScript/Vite build passes. Image manifest-list digest sha256:ab918fb2a577cfe9a950f93bf9f286b96370c9b0d46dc1f4f7b7498ff1eeb44e. This supersedes the earlier build-in-progress note. Final SSH retry still fails during banner exchange; no remote backup, migration, image upload, traffic switch or live latest-version acceptance occurred. Existing HTTP health remains200/ok/runtime true. Deployment remains pending server access and actual configuration/backup validation; this is not an enterprise release acceptance.


Deployment staging continuation (2026-10-01): SSH recovered. Latest application94bfcd7 is built on the target server, protected database/files backups exist, a restored copy successfully migrates0→10, and all13 baseline business tables compare exactly. Private candidate API/runtime/broker health and registration/login/Secure-HttpOnly-cookie/project CRUD subset pass. Production database and traffic remain unchanged. Public443 and temporary-domain certificate validation fail at cloud ingress/domain boundaries; user action requested, TLS candidate stopped to avoid repeated orders. See specs/008-sandbox-broker/deployment.md for exact images, backup hashes, scope, failures and remaining cutover/rollback gates. Do not mark deployment or enterprise acceptance complete.


Live candidate generation gate (2026-10-01): real configured model planning succeeded, but build failed with missing index.html and zero committed files. Persisted events show simultaneous glob/read calls first reported unknown outcomes, then all writes were denied because the lease became uncertain. Source inspection identified the per-process broker transfer admission rejects overlap while model read tools explicitly execute in parallel. BrokerSandboxClient now serializes file requests per lease through a FIFO bounded to16 admitted calls, including the active request. Queue waiting shares the existing request timeout and caller cancellation; cancelled/expired queued work is never dispatched. Unknown dispatched outcomes still poison the lease and suppress queued requests without retry. Thirteen actual loopback HTTP/client/lifecycle regression tests pass, including overlapping intake, bounded capacity, queued cancellation and failure suppression. Pi1905 files verify unchanged. Evidence: .logs/broker-file-queue-tests.txt. This fixes client admission rather than weakening broker isolation. Rebuilt candidate/live-model retest and public ingress acceptance remain pending; no task is marked complete and old production traffic is unchanged.


Server live generation retest (2026-10-01): candidate updated to e00da8d34b8f34e0b210654bb6ebc8f64549307e, image sha256:9b16ac78266598b2af7be45beff914764430f7852207706487c6b243bc5a4f7e. Using the real configured provider/model and own runtime/broker, a fresh acceptance account completed planning, approval and generation of the requested standalone counter. Terminal project is ready, latest run done, one committed file, nonempty registered revision and authenticated preview HTTP200/3479bytes. All8 recorded broker attempts are terminated and API health reports runtime/broker true. Persisted before/after results: /home/ubuntu/atom-backups/release-94bfcd7/live-before-queue.json and live-after-queue.json. No test password, session token or provider credential was recorded. Candidate containers now use bounded10MiB/3-file logs. This supersedes the live-model-retest-pending note for this small real workflow only; browser interaction, existing-project bulk import, TLS and final quiesced cutover remain pending. Public HTTPS still timed out on this turn; old production traffic remains unchanged. Full enterprise completion/T034 is not accepted.
