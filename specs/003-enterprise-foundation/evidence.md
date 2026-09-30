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

## Continuation — repository contract and isolation reproduction

Previous turn was progress: commit 3fd0362 includes provider fix, research, contracts and database experiment. Re-read current worktree and constitution; only pre-existing routers/__init__.py was dirty at entry. Added collaboration.md revision 1 with explicit CO-01…07 acceptance scenarios, all unexecuted. Reviewed Atoms environment-secret fallback and separate build/runtime billing documentation; no paid action or connector authorization occurred.

T023 Windows command in runtime: `node --import tsx scripts/probe-local-isolation.ts`; 0.28 seconds, exit 1, `NO_OS_ISOLATION`. A Node child through actual LocalSandboxClient.exec saw a randomly named synthetic environment value and read a freshly created canary outside its assigned workspace. Values/paths not printed. Temporary root containment verified before cleanup, sandbox registration removed and synthetic environment variable deleted in finally.

Linux confirmation used local `node:24.16.0-bookworm-slim`, `--pull=never --network=none --read-only --user 1000:1000 --cap-drop=ALL --security-opt=no-new-privileges --memory=256m --pids-limit=64`, runtime source mounted read-only and bounded /tmp. `node --experimental-transform-types scripts/probe-local-isolation.ts` produced the same exit 1 / NO_OS_ISOLATION in 0.90 seconds; Node emitted an experimental-type-transform warning. Container removed automatically. The outer container confined the experiment; the inner LocalSandboxClient workspace did not confine its child. No real host canaries, production files, credentials, model calls or network requests inspected.

Scope limit: this directly invokes the sandbox abstraction with a fixed probe command. It does not prove prompt injection or arbitrary shell access through current builder tools. server.ts line 129 restricts workspaceToolNames to five file tools. The next isolation implementation must preserve those tools while moving file/command execution behind a policy-enforcing boundary, with own runtime and Pi unchanged. No isolation fix or enterprise acceptance is claimed by these failing probes.

Additional authenticated browser research: revisited actual empty my-projects list, navigated dashboard to the public Hello World Discover example, and opened its separate live application. Embedded and top-level page both rendered. A09/A10 recorded in research.md, with boundaries. No clone/save/generation/publish action or credit consumption initiated. Existing cloud-console tab did not establish the designated server's identity; no terminal command entered and no host key trusted from it. Production infrastructure verification remains open.

Pi lock verification re-run after adding the reproduction script: 1905 files passed at f07218c4d4bbc12bef056a7058c3dd49dfe41abe. Whitespace check passed; no product implementation changed this turn and no prior test result is represented as new enterprise acceptance.

## Subsequent continuation — configuration and runtime authentication

Implemented child 005 with explicit independent service/session secrets, safe validation errors, production cookie/transport guards, authenticated runtime health/roles/run/cancel and honest 503 runtime readiness failure. 104 backend cases and 6 runtime tests passed; frontend build, Pi lock and deployment-script syntax/config parsing passed. Child evidence.md records initial failures, health refinement, CRLF correction and limits. No production script executed. This closes a narrow configuration gap, not parent SEC-06 in full (origin/CSRF and other policies remain open), SEC-05 or enterprise delivery.

## Continuation — validating a replacement isolation profile

Previous turn classified as progress: 050faba/c3b625b changed configuration/authentication behavior and synchronized tested status. Current tree rechecked; only user's routers/__init__.py modification existed at entry. Inspected SandboxClient usage, actual Python file-tool command builders, backend workspace/race/session layout and runtime destroy lifecycle. Proposed isolation.md now records the broker/grant boundary, bounded filesystem, snapshot checkpoint and crash/cancel integration requirements. No production broker has been implemented.

Official Python image was missing locally; pulled docker.io/library/python:3.12-slim-bookworm, resolved digest `sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e`. Command: `backend/.venv/Scripts/python.exe scripts/research/probe_container_limits.py --image python:3.12-slim-bookworm`. Exit 0 in 2.45 seconds, scope container-profile-only. Script resolves image ID, publishes no ports, mounts no host directories and uses no real credential.

Observed UID 1000, synthetic parent environment value absent, Docker socket absent, root filesystem write denied, direct network connect returned ENETUNREACH, 8 MiB workspace overflow returned ENOSPC, bounded child creation hit EAGAIN after 30 children, 256 MiB allocation under 128 MiB memory cap exited 137 with cgroup oom_kill counter increment. Previously written allowed file remained readable afterward. Child processes and disposable container were removed; subsequent filtered container list empty.

Limits: 0.5 CPU setting was configured but not load-measured; 90-second independent lifetime was configured but not elapsed-tested. This does not test grant authorization, hostile archive handling, source snapshot import/export, current Pi/file tools through a broker, cancellation/crash recovery, public multi-tenant kernel isolation or live generation. T025 closes only the documented mechanism experiment, never SEC-05. No host escape test against real data occurred. Important implementation consequence: a writable host bind does not satisfy a disk quota; bounded workspace and committed snapshot promotion must be designed together.

## Continuation — verified snapshot component

Child 006 implements versioned bounded manifest/raw-byte transfer, verified private staging and Linux no-follow export with real link/special-file rejection. Final backend JUnit: 179 cases including subtests, 5 Linux-only skips, no failures/errors; those Linux cases ran separately in the pinned Python container (20 methods, 19 pass, one non-Linux-only skip). Independent code review found cleanup error redaction and Windows reserved-device omissions; fixed and tested. Child evidence records commands, failed pre-implementation collection and exact scope.

T026 accepts only the component. No runtime/API caller, broker, grant, fencing or crash janitor has been implemented, so SEC-05 remains unaccepted and T027 records the next integration gate. Frozen source and service-private parent are required; tmpfs quiesce/export lifecycle needs real validation. No current workspace, Pi source, credentials or production data were changed; no GitHub push/deployment occurred.

## Continuation — actual snapshot transfer across container lifecycle

Previous turn was progress: commit a74565d added the verified snapshot component. Rechecked current worktree; only preexisting routers/__init__.py user change remained. Inspected current ProductAgentRuntime create/destroy and server recovery paths; sandbox allocation precedes several unguarded initialization operations, and destroy has no completion outcome. These are explicit T027 design inputs, not repaired by the probe.

Command: `backend/.venv/Scripts/python.exe scripts/research/probe_snapshot_lifecycle.py --image python:3.12-slim-bookworm`. Exit 0 in 3.81 seconds; local image ID `sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e`. Disposable UID 1000 container, readonly root, no network/host mounts/ports, 128 MiB memory, 32 PIDs, two 8 MiB tmpfs mounts, independent 90-second lifetime. All test data synthetic; actual 006 module transmitted via stdin/control source, not a test replacement.

Observed: live export verified by host receiver; expected HTML and all 256 binary byte values preserved; excluded .env absent; stopped state confirmed; restart lost tmpfs workspace; actual receiver restored snapshot inside running container; re-export exactly matched original bytes and revision `a7e0ba0295b1472e63e931e4d6b4bd2e51aaf22f73363083510f59e923570489`; original host snapshot unchanged; labelled container removal and empty filtered inventory confirmed. Probe cleans uncertain-create outcomes by checking its unique ownership label, not by assuming a successful create response.

Interpretation: checkpoint while alive after a proven writer barrier, before destroy. Immediate abort/OOM can discard uncheckpointed output; retain last committed revision and report loss. No arbitrary child writer, broker grant/registry, runtime file-tool call, cancellation, daemon outage or process-crash recovery was tested. T028 is only lifecycle mechanism evidence. No product behavior changed in this continuation; no previous broad test result is claimed as fresh acceptance.

## Continuation — runtime sandbox ownership fix
Previous lifecycle experiment was progress (42419d9). Child 007 reproduced an actual runtime initialization failure leaving destroy count 0 after acquisition, then introduced one outer ownership scope. Final runtime suite: 14 passed, no skips; real Pi recovery additionally checks two acquisitions/two releases and one retained write. Pi lock: 1905 files unchanged. Single and dual release failures cannot produce success; both callback and release causes retained. All test failures, corrected invocation cwd and fixture timeout are recorded in child evidence.

T029 closes only own-runtime adapter ownership. Docker termination, broker registry/grants, explicit checkpoint/fenced revision path and crash reconciliation remain T027. No GitHub push or deployment yet; preexisting user router edit preserved.

## Continuation — broker specification and strict grant component
Created child 008 with full broker stories, dependency-ordered tasks and explicit typed-file-operation migration. Implemented fixed HS256 signed scopes with strict schema/purpose/time/size validation and actual cryptographic tampering tests. Final backend JUnit: 215 cases including existing subtests, 0 failures/errors, 5 existing Linux-only skips; 36 new grant cases pass. Child evidence distinguishes verified codec from unimplemented HTTP zero-effects/admission/revocation checks. T027 remains open; no runtime service switch or production isolation claim.

## Continuation — durable broker ownership registry
Child 008 T003 now implements real SQLite versioned ownership, idempotency, revocation, head/version fencing and termination-state recording. Seventeen component cases passed, including 24 concurrent duplicate admissions and abrupt child-process exit preserving committed state/rolling back uncommitted revoke. Full backend regression recorded 232 cases including subtests, no failures/errors, 5 existing Linux-only skips; final target-type refinement passed component rerun. Contract/evidence distinguish registry transitions from actual Docker termination and future in-flight operation serialization. T027 remains open; no runtime switch, push or deployment.

## Continuation — actual fixed-profile Docker driver
Child 008 T005 now creates/reuses/inspects/terminates only labelled owned containers with pinned local image and validated resource settings. Real memory/PID/disk/network/CPU-throttling/readonly/nonroot checks, independent deadline exit, peer survival, policy-upgrade cleanup and no-restart cases passed. Driver/process combined suite 14 pass; full backend JUnit 246 cases with 10 explicit skips, no failures; final guard changes revalidated by all 5 actual Docker integration tests. Initial output-drain and expiry-boundary test failures are retained in child evidence with their fixes. Final labelled container inventory empty. This does not close HTTP admission, registry-driver reconciliation or Pi/tool integration; T027 remains open.

## Continuation — known-attempt broker lifecycle
Child 008 now connects registry/driver for process ownership, known-attempt startup retirement, duplicate provisioning, revoke/expiry and unavailable-daemon recovery. Six actual Docker lifecycle scenarios pass; Windows/Linux cross-process leases verified. Combined lifecycle/registry/lease tests 24 passed; backend JUnit 253 cases, no failures/errors, 16 explicit platform/opt-in skips. T006 intentionally remains open for durable unknown-orphan handling, service scheduling and in-flight operation integration. T027 and all enterprise deployment/HA gates remain open. No production behavior switch, push or deployment.

## Continuation — durable orphan recovery and registry migration
Child 008 now persists orphan discovery before removal, revalidates full-ID ownership, records unknown outcomes and recovers confirmation after actual process death following container deletion. Conflicting ownership remains untouched and blocks readiness. Transactional v1→v2 migration preserves prior ownership/revocations and rolls back failed validation. Combined real registry/lifecycle/driver/lease suite: 35 passed, no skips. Backend regression: 259 JUnit cases including subtests, no failures/errors, 19 explicit skips; 14 opted-in Docker cases executed separately. Child evidence records exact commands/limits. T006 stays open for service scheduling and in-flight operations; parent T027 and delivery gates stay open. No runtime switch, push or deployment.

## Continuation — independent broker control service
Child 008 T004 now provides explicit isolated configuration, separate admin authentication, bounded/redacted HTTP input, actual container provisioning/revoke, loopback-only entry point, lifespan recovery and periodic expiry. Five real service/Docker cases include TCP HTTP transport, automatic expiry, daemon recovery and missing-image denial; twenty config/boundary cases include real five-second stream timeout. Final complete backend run enabled all Docker tests: 284 JUnit cases including subtests, 0 failures/errors, 5 existing Linux snapshot skips, 75.499 seconds; all 19 Docker cases executed and final inventory empty. Initial collection/concurrency failures and fixes are recorded in child evidence. T006 remains open for in-flight file operations and deadlines; runtime/snapshot integration, T027 and delivery remain open. No production adapter change, GitHub push or deployment.

## Continuation — fixed file-operation executor
Child 008 now has a real bounded Linux file helper and trusted driver adapter, eliminating caller-supplied shell/source from this component. Tests verify exact binary/UTF-8/range/search behavior, 8-MiB transfer, path/link/device/casefold boundaries, concurrent conditional writes, ENOSPC preserving prior bytes and independent regex timeout. Full backend with Docker enabled: 308 JUnit cases including subtests, no failures/errors, 5 existing Linux snapshot skips; final helper refinements revalidated by 33 targeted cases with no skips. All test containers removed. T007 remains open: runtime wrappers still use the old port and must migrate; operation authorization/receipts/cancellation and snapshot integration remain unaccepted. No new file HTTP route, production switch, push or deployment.

## Continuation — runtime structured file-tool migration
Own runtime file wrappers now use typed operations with no exec fallback, validate returned identity/hash/size, and make Pi Edit conditional on its original bytes. Group forwarding and explicit local development adapter migrated. All 16 real Node runtime/Pi/filesystem/recovery cases and 77 selected policy/tool Vitest cases passed; Pi source 1905-file SHA verification passed. Dependency findings discovered during test setup were repaired with pinned Vitest 4.1.11/Undici 8.10.2; clean temporary lockfile install and root dependency audit passed, without editing Pi or claiming bundled-artifact audit. Child evidence records setup failures/repairs. Broker operation authorization/receipts/cancellation, snapshot flow and production selection remain open; parent T027/release gates unaccepted, no push/deploy.

## Continuation — durable broker operation receipts
Child 008 now persists bounded schema-v3 operation receipts and uses current attempt authorization around real helper execution and result commit. Real Docker tests cover duplicate write delivery, changed-request/cross-attempt denial, post-write commit failure, process death and concurrent revoke/late completion. Full backend regression: 316 JUnit cases, 0 failures/errors, 5 existing platform skips, 105.164 seconds. Detailed fault boundaries and fixture-only ready transition are recorded in child evidence. T027 remains open for actual HTTP/Pi integration, seed/checkpoint/revision flow and production acceptance. No GitHub push or deployment.
