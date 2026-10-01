# Feature Specification: Isolated sandbox broker
Branch `codex/008-sandbox-broker`; created 2026-09-30; status **in progress, not accepted**.
Input: parent 003 isolation/execution contracts; actual container quota, snapshot and runtime lifecycle evidence.

## User Scenarios & Testing
### US1 — Authorize only the intended work (P1)
Operator issues a finite permission for one organization/project/run/attempt and input revision. Runtime cannot alter it to access another workspace or choose host resources.
Independent acceptance: valid authorized file operations succeed; forged/expired/wrong-purpose/wrong-scope/revoked permissions produce no container or file mutation.

### US2 — Bound and recover execution (P1)
Operator can cancel work or restart the service without leaving indefinite execution or accepting stale results.
Independent acceptance: real timeout/cancel/restart/daemon failure tests preserve durable ownership and confirm termination before replacement. Unknown termination fails readiness and dispatch.

### US3 — Preserve verified work through existing tools (P1)
Project owner uses current write/read/edit/glob/grep and recovery, with verified snapshots preserving results across isolated attempts.
Independent acceptance: actual Pi and file tools through broker/containers; byte-exact input/output snapshots; failed or stale promotion preserves prior revision; cancellation reports uncheckpointed data loss accurately.

### Edge Cases
Duplicate creates, same identity/different grant, lost create response, worker or broker crash, expiry during operation, stale fencing token, output flooding, symlink/path attacks, quota/OOM, interrupted checkpoint, previously acquired sandbox not released, daemon unavailable, partial adoption/migration.

## Requirements
- FR-001: Signed permissions MUST bind organization, project, run, attempt, input revision, fencing token, supported profile and finite lifetime. Verification MUST reject malformed/forged/expired/future/wrong-purpose scopes without side effects.
- FR-002: Service authentication and permission-signing keys MUST be separate from runtime/session/model credentials. No platform secret, Docker authority, host path, image or resource flags may be supplied by the workload.
- FR-003: Ownership intent MUST be durably recorded before creation; duplicate equivalent requests return same attempt, conflicts fail. Revocation/current fence/state MUST be checked on every operation.
- FR-004: Actual OS/resource/egress limits MUST apply. Each attempt has a finite independent lifetime and bounded operation input/output/deadlines.
- FR-005: Cancellation/restart MUST reconcile owned containers, persist confirmed or unknown termination, prohibit further mutation and reject dispatch while unsafe. Orphan removal MUST follow durable discovery and full-ID ownership verification; pending observations survive deletion/confirmation crashes without fabricating grants or revisions. Versioned registry migration MUST preserve prior ownership and revocations or roll back completely.
- FR-006: Normal completion MUST quiesce writers while alive, verify export, fence revision registration, then destroy. Failure preserves previous committed revision; no implicit publication in destroy.
- FR-007: Own runtime and existing file tools MUST use the broker; production MUST fail closed without it. Explicit development local mode remains visibly non-isolated.
- FR-008: Real integration, fault injection and deployment migration evidence MUST precede acceptance. No component test may close whole feature.

FR-007 runtime acknowledgement: Node MUST correlate confirmed completion to the trusted API-attempt/workspace/broker-attempt/grant/deadline and a valid registered receipt. HTTP 200 with cancelled/failed/timed-out outcome or missing receipt is not successful completion.

FR-007 completion HTTP: complete/cancel requests MUST derive their target solely from verified execution-purpose claims and compare every immutable persisted binding plus current ownership before effects. Only confirmed closed results may return success; transport or storage failures must not be presented as accepted output.

FR-007 completion authority: runtime completion MUST use an independently scoped execution capability; sandbox grants and administrative credentials must not authorize that boundary. Purpose, exact persisted scope, owner, fence and deadline must be checked before action. Issuance alone is not completion acceptance.

FR-007 lease preparation: a ready runtime lease MUST derive from a persisted reservation and verified immutable base, bind the actual broker identity, and pass a fresh dispatch check. Ready replay must not reseed; preparation failure must never return a lease or imply successful completion.

FR-005 cancellation ordering: committed API cancellation MUST precede administrative revocation; confirmed closure MUST follow verified broker termination. Transport uncertainty or caller cancellation must not release the active slot. Concurrent already-closed outcomes and receipts remain unchanged.

FR-005 recovery visibility: trusted owner-checked cleanup reads MUST remain available after cancellation, expiry, registration and closure without granting dispatch, releasing ownership or changing any persisted outcome. Cancellation returns committed cleanup identity; closed-attempt retries preserve successor state.

FR-005 terminal recovery: the coordinator MUST durably decide its intended outcome before releasing the worker. A pending decision is not a terminal result and retains ownership; recovery repeats verified termination before closure. Explicit cancellation may override nonclosed success intent.

FR-006 completion recovery: persisted receipt recovery MUST compare the current broker checkpoint digest and actual immutable artifact before skipping export/confirmation. A cancellation committed before final success closure MUST prevent succeeded outcome even when a revision already exists.

FR-006 registration semantics: a durable checkpoint, a successfully terminated execution and independently accepted product output are separate facts. A later failed/cancelled run must preserve any committed revision without being reported successful. Lost acknowledgements must resolve an immutable receipt; retries must not advance a newer head. Unknown termination retains ownership until reconciliation confirms release.

FR-006 migration prerequisite: reject unsupported API schema drift, preserve existing business rows, create a verified exclusive backup before transactional changes, and recover interrupted DDL. New scoped workspace heads start empty; legacy status cannot invent verified artifacts, accepted revisions or terminated attempts. Offline migration alone does not satisfy revision registration or application adoption.

## Key Entities
Trusted control-plane transport cannot infer durable success from HTTP headers or automatically replay uncertain mutations. It must verify complete bounded responses, exact attempt/deadline/version and both archive/semantic digests. Administrative credentials/signing authority stay outside runtime leases. Execution intent must be durably reserved before provisioning and later bound to one broker identity. Repository and real component integration now exercise that ordering; production coordinator/application adoption remains unaccepted.

Administrative checkpoint transfer requires independent admin credentials plus a scoped grant; runtime tokens alone cannot export or confirm. Large export responses retain the shared transfer slot through bounded delivery and release it on transport failure. A partial response is not durable storage or registration acknowledgement. The caller must obtain an actual API receipt before asserting a registered digest over the administrative confirmation route.

Verified artifacts must be immutable and durably acknowledged before any revision head can advance. Local storage uses exact-byte digest identity separate from the canonical revision digest; no materialization or registration is implied by storage. Offline API migration and trusted execution/revision repository now exist; production adoption remains an explicit prerequisite in contracts/revision-registration.md.

Verified export serializes with file operations, durably enters quiescing, exports while the worker is alive and verifies every returned byte before delivery. Repeat export is read-only and requires current authorization. An in-memory verified export is not a stored artifact or registered revision. Explicit trusted confirmation after durable registration rechecks export bytes/scope/version and current authority before checkpointed; it never implicitly releases the worker (contracts/checkpoint-export.md).

Runtime broker adapter is bound to one trusted pre-seeded lease and contains no administrative credentials. Acquisition verifies live ready status; failed acquisition attempts cleanup. Unknown transport outcomes prohibit new calls; release succeeds only with matching confirmed termination. Scoped release may repeat cleanup of its own immutable attempt despite revocation, but cannot act on a successor or grant new authority (contracts/runtime-adapter.md).

HTTP seed/file intake authenticates before consuming large bodies, checks current ownership before intake and dispatch, and serializes large transfers with immediate busy rejection. Admin seed credentials and runtime grant authority are distinct. Known operation failures remain explicit outcome values; transport success alone is not business success (contracts/runtime-http.md).

Input initialization requires a verified ATOMSNAP1 stream matching the grant's exact base revision. Only provisioning attempts may receive it; no merge into an existing workspace. Ready is committed only after successful validation/promotion and a fresh ownership/version check. Failed or uncertain imports retire the attempt; ready is not output revision registration (contracts/seeding.md).

File-operation retries must bind an operation ID to the exact request and current authorized attempt. Completed responses may be reused within bounded durable storage; uncertain effects must not be replayed. Revocation/expiry deny late completion and recovery retires prior workers before new dispatch (contracts/operation-receipts.md). This component does not establish end-to-end runtime acceptance.

Grant, broker attempt registry, operation receipt, immutable snapshot, registered revision, terminal outcome with termination status.

## Success Criteria
- SC-001: All negative authorization cases cause zero container/file effects.
- SC-002: Real duplicate delivery and restart tests retain one owned attempt; stale operations cannot register output.
- SC-003: Existing real Pi/file-tool scenarios pass through actual containers with exact snapshots.
- SC-004: Cancellation/timeout and orphan reconciliation are measured against configured deadlines; unknown outcomes are visible and prevent unsafe replacement.

## Assumptions
Initial deployment is a single trusted private-team Docker host, not a hostile public multi-tenant isolation claim or HA milestone. Broker-local registry is separate from future PostgreSQL control-plane execution ownership. Paid models and full enterprise release remain parent gates. First profile only permits controlled file helpers; arbitrary user shell/background processes and dependency-network access are excluded until separately designed.

FR-007 lifecycle ownership: one sandbox acquisition and one final checkpoint MUST cover the entire model recovery sequence. Work results must not return before verified completion and cleanup; failures preserve their original and cleanup causes.

FR-007 external scope: ProductAgentRuntime MUST reject a different run before session effects and MUST NOT destroy a sandbox owned by an outer execution lifecycle during internal recovery or failure.

FR-007 production selection: production runtime MUST require broker mode, configured trusted origins and matching ready leases, with no local fallback. Terminal result delivery must follow registered completion and expose the verified revision receipt.

FR-007 API acknowledgement: leased runtime success MUST match an owner-scoped durable confirmed successful receipt before the API yields the terminal result. Missing, mismatched or uncommitted runtime receipts must be rejected.

FR-006 workspace identity: new committed projects and race heats MUST obtain an owner-checked durable workspace identity without fabricating artifact or revision evidence. Concurrent retries preserve identity and existing execution/head state; foreign heat membership is denied.

FR-006 initial import: trusted quiescent legacy workspaces must be exported and stored as verified immutable bytes before root registration. Exact replay must preserve identity; changed input must not reset an existing root or head. Import must reject source roots containing control-plane database or artifact storage.

FR-005 startup recovery: before broker-backed API admission, interrupted attempts must be enumerated from the durable ledger and revoked with separately confirmed termination. Preserve already-decided outcomes and receipts; absence of a success decision is not success. Capacity exhaustion, timeout or uncertain termination must prevent readiness.

FR-007 application startup: production requires broker mode and explicit separate broker/completion credentials. The API must hold exclusive host-local database ownership while recovering and serving, refuse unsafe or unmigrated databases, expose scoped completion/cancellation only after recovery, and reject dispatch without a prepared lease. Health must include authenticated broker readiness.

FR-006 committed read identity: validation and preview must identify the registered immutable revision whose bytes they read. Owner-scoped reads must not silently fall back to the old mutable workspace. An explicitly expected revision mismatch is a conflict; temporary read extraction must be cleaned on normal and exceptional exit.

FR-006 preview/file adoption: broker-mode preview and source-file routes must read committed artifacts and identify the revision in response headers. Missing service/version or corrupt artifacts must not fall back to mutable files. Draft previews, including heats, require ownership even when the project has a published slug.

FR-006 catalogue consistency: broker-mode project detail and race responses must derive file lists/counts/bytes and preview availability from verified committed manifests, expose revision identity and never list uncommitted host files. An uninitialized scope reports revisionId=null and an empty list. File timestamps must identify their actual source rather than inventing filesystem modification times.

FR-007 application dispatch: after committing the current Run, broker orchestration must establish workspace identity, import a real initial source only when no head exists, reserve durable dispatch authority before provisioning, and deliver the prepared lease. Later turns must seed from the registered head. Successful engineering turns must validate the exact returned committed revision, not the legacy directory. Failure/timeout/cancellation must request confirmed scoped cleanup and preserve unknown ownership. The application/broker profile permits at most 7200-second capabilities, with 60 seconds reserved beyond the turn budget for completion/cleanup.

FR-005 active-model interruption: the runtime must distinguish explicit cancellation from its own elapsed deadline in error status, never emit a result for either, and allow independent cleanup to finish. API Run and single-project planning/build status must preserve cancelled/timed_out rather than collapse them to ordinary failure. Unregistered writes must not replace the last committed version.

A deadline observed after durable artifact registration but before the runtime response MUST prevent a successful Run/project outcome. The already committed revision and receipt remain valid; execution cleanup success is distinct from timely run completion.

Cancellation request lifetime MUST NOT own cancellation cleanup. Disconnecting either the initiating caller or a duplicate waiter must not send another cancellation into the run cleanup. Shutdown must await owned cleanup even after the run job has left its job map.

FR-006/FR-008 refinement: enterprise acceptance must bind exact artifact, contract and trusted verifier identity. Publication/adoption require fenced immutable revisions and atomic release pointers. Timestamp/client-reported checks cannot authorize release. contracts/revision-release.md defines the unimplemented requirements.

FR-006 next-version migration prerequisite: verified backups must retain the exact supported source schema (baseline or v1), include committed WAL, exclude concurrent writers during capture, and refuse overwrite/drift. Backup verification must explicitly select the expected version rather than accepting any version.

FR-006 migration extension: explicit target v2 may add verification/release identity tables while preserving exact v1 business and journal records. Original evidence is not backfilled or promoted. Runtime startup remains v1-only until repositories, verifier and application adoption pass their gates.

Verification contract identity includes ordered requirements/checks/setup, title/detail, selectors and exact input/expected text. Strict versioned encoding rejects unknown fields, duplicate keys and invalid Unicode; it must not silently repair or discard checks. Complete results require exact unique check identities and actual booleans.

Verification intent reservation must capture the stored project contract under the same writer transaction as owner/current-head/idle checks. Exact request replay preserves original identity and deadline; replay is historical evidence, not renewed dispatch permission.

Verification result registration derives outcome/counts from exact complete coverage of the captured contract. A first report outside the original time interval is rejected. Exact historical replay retains the original timestamp; changed report content conflicts. Persisting a report does not publish or prove verifier authority.

Verification interruption must persist cancelled/timed_out separately from observed check results. A report and interruption racing for the same request can commit only one immutable terminal result. Expiry inventory must be bounded and reject capacity overflow without partial mutation.

Release metadata promotion must recheck owner, idle main workspace, expected head, current contract, passing evidence, policy and runner in the same transaction that advances the publication generation. Release record, pointer and idempotency receipt commit together; historical replay must not repromote old content.

Unpublish must compare expected release and generation, atomically disable visibility and save an idempotency receipt, preserving artifact/history. Exact historical replay cannot disable a subsequently published release.

Pinned published artifact lookup requires an active current publication and authorization under both the current release audience and the selected historical release audience. Unpublish denies even owner-facing publication paths; draft preview remains a separate route.

Published materialization must verify actual immutable storage bytes against recorded semantic digest and size, never fall back to legacy directories, and clean private temporary output on normal/error exit. Recheck current visibility after storage IO before yielding a captured version.

Published view materialization must bound concurrent in-memory snapshot reads and extraction. Current single-process profile permits one active view with a three-second admission wait; capacity is released after normal/error exits. Reauthorize the pinned release after extraction before returning it.

T017 content isolation refinement: generated content must use a dedicated content site and durable per-version host binding. Root-relative resources must resolve within the same pinned artifact. Console credentials and direct DOM-based acceptance must not cross the content boundary. See contracts/content-origin.md; requirements remain unimplemented.

Content origin binding uses an immutable opaque route identity scoped by project and release, unique per release; invalid route syntax and cross-project mapping must fail at the database boundary. Offline migration must preserve prior version definitions and journal history.

Content binding allocation must be owner-scoped and idempotent by immutable release, use an opaque unpredictable identifier, and reject collisions without retargeting. Resolving a binding must reapply current publication authorization; the identifier itself grants no access.

Content host routing requires exactly one Host authority matching r-<32 lowercase hex binding>.<configured suffix>, with only the optional standard HTTPS port. Forwarded-host metadata cannot supply route authority. Syntax validation does not establish DNS/TLS/site isolation.

Public content implementation increment: requests resolve an immutable content binding, recheck live/current and pinned visibility around artifact IO, and read verified snapshot bytes. Anonymous access only; console cookies and bearer headers confer no authority. Missing resource paths remain 404; navigation fallback applies only to extensionless final path segments. Production ingress, private access, browser behavior and verifier acceptance remain unimplemented gates.

Pinned serving validation now includes actual differing HTML/CSS snapshots across promotion between requests. Range/conditional hints do not bypass live audience checks; this static component intentionally returns full responses rather than implementing partial/cache validation responses. Browser and deployment acceptance remain separate.

Content transport increment: configured per-instance active-response admission covers worker read plus delivery, rejects excess requests without scheduling IO, and bounds ASGI sending. Cancellation while IO runs cannot release the resource slot early. This does not promise cancellation of an OS file operation, socket connection admission, graceful process shutdown or distributed limits; those remain open deployment requirements.

Content lifecycle increment: ASGI shutdown closes admission permanently for the instance and waits for admitted IO/delivery ownership within a validated deadline. Pending work produces shutdown.failed; a caller cancellation is not proof that its worker stopped. Tests exercise successful/failed drain and real Linux loopback HTTP startup/serving/shutdown; production supervisor and TLS/browser requirements stay open.

Browser policy validation now separates three evidence layers: real artifact/ledger tests, actual ASGI/TCP lifecycle tests, and Chromium policy attack fixtures. The latter reuse production HEADERS but intentionally do not impersonate artifact or authorization implementations. Full composition, private sessions and independent browser-verifier authority remain required before release acceptance.

Stable sharing now resolves only current live public releases to their exact existing binding, with no-store 307 and no client-controlled redirect target. Private/offline states return 404; missing current binding returns 503. No anonymous read creates a binding or revives a prior release. Public sharing is implemented internally; private handoff and production ingress remain open.

Browser composition evidence now covers a real immutable artifact page with eight root-relative styles and eight scripts, served through Linux ContentService and a local test TLS ingress. Default response capacity is eight following a reproduced one-slot browser failure; underlying materialization remains bounded separately. Arbitrary load, public ingress/private access and trusted verification are still unaccepted.

New v3 release promotion now atomically persists its content binding with the immutable release, pointer and receipt. The publish-to-binding availability window is removed for these new releases. Historical migrated releases still require an explicit authorized binding; anonymous sharing never mutates state. Tests establish transaction behavior, not verifier authority or overall publish acceptance.

Private access change contract: contracts/private-content-access.md defines a browser-bound bootstrap/handoff/session protocol, source console-session revocation and publication-generation invalidation. Current subject-only JWT and cookie-deletion logout are insufficient for those properties. Durable console sessions and explicit reauthentication cutover are prerequisites, not implemented compatibility behavior. Top-level and embedded access both remain required; embedding has a separate browser-policy gate. No private access acceptance is claimed.

T020 schema increment: explicit offline v4 stores durable console sessions and hash-only content bootstrap/handoff/session records. Constraints bind source user/session, bootstrap/binding and consumed handoff/session generation, cap lifetimes and prevent scope changes or terminal-state reversal. Existing console authentication and content serving do not accept v4 yet; no private access enabled.

Durable console-session component now creates bounded per-user active sessions, validates persisted user/session scope and absolute expiry, and revokes idempotently. Before-issuance clock readings fail validation. This trusted repository does not validate passwords/JWT signatures or expose HTTP authentication; those remain T022 prerequisites for callers. Historical expired rows are not extended or silently removed.

Private capability repository increment: browser bootstrap, authenticated-caller handoff issuance, one-use atomic exchange and current-source/generation authorization are implemented internally. Raw 256-bit secrets are returned only to the caller; database values are purpose-separated SHA-256 digests. Concurrent redemption has one winner; wrong browser/scope and failed transactions do not consume valid pending credentials. HTTP transport, trusted caller authentication, ingress rate limits and cleanup remain unimplemented.

Durable credential increment: a separate signed-console credential component binds issuer/audience/type/version, user, durable session ID and exact stored issuance/expiry. It checks signature before session lookup, rejects legacy subject-only credentials and honors stored revocation. Storage/schema failure is propagated as unavailable rather than being represented as authentication denial. Legacy login/cookie routes are not switched.

Private serving increment: ContentService can explicitly receive a same-database ContentAccessRepository. It reads only the dedicated __Host-atom_content opaque cookie, rejects malformed/duplicate credential input, and repeats current session/source/generation checks before IO, after artifact read and after extraction. No credential means existing public-only authorization; console cookies never become private authority. No exchange endpoint, cookie issuance or main application cutover is enabled.

Content namespace requirement (T023): root `_atom` is reserved case-insensitively for service-owned authentication paths. A conflicting root file or subtree rejects the entire content manifest; never silently remove or rewrite project files. Nested `_atom` and unrelated prefixes remain valid. Reserved HTTP paths must not fall back to generated SPA content. Serving enforcement exists; publication preflight must still enforce this before pointer promotion.

Content publication preflight must reject missing, corrupt, descriptor-mismatched or namespace-conflicting snapshots before creating release/binding/pointer/receipt rows. Authorization, head/idle, current evidence and publication generation must be rechecked after storage IO. Exact committed replay returns the original receipt without requiring artifact availability and must not republish an offline release.

T023 HTTP exchange increment: exact /_atom/exchange is service-owned. HTTPS GET/HEAD serves a fixed fragment-clearing page with hash-authorized script and no generated content; HTTPS same-origin POST accepts exactly one 64-byte lowercase-hex handoff in application/octet-stream, requires the dedicated bootstrap cookie, atomically exchanges and returns only HttpOnly cookies with empty 204. Invalid metadata/body cannot consume a handoff. Intake shares response admission and has a finite deadline. Bootstrap and console issuance remain prerequisites, not fabricated login.

T023 bootstrap endpoint: configured private content service accepts canonical HTTPS top-level navigation GET /_atom/bootstrap, persists a bounded nonce, sets only the host-only Secure HttpOnly Lax bootstrap cookie and redirects to a fixed configured console /content-access path with public binding/challenge. No arbitrary return URL, HEAD mutation, subresource/iframe/prefetch bootstrap or authenticated artifact output. Console login/action/issuer remains a separate required gate.

T022 console cutover increment: explicit durable session mode requires pre-migrated v4 and canonical configured HTTPS console origin, Secure root cookies, dedicated __Host-atom_console credential and no acceptance of legacy JWT/cookie. Successful password login/register creates durable source session before signing; every authenticated API dependency verifies persisted status; logout revokes before cookie deletion. Mutating auth requests require exact same-origin HTTPS context. Store failure returns unavailable without false logout success.

Runtime v4 compatibility requirement: main revision operations must preserve their v1 transaction/fencing/recovery invariants on exact verified v4 while coexisting with durable console records. No automatic schema upgrade or relaxed drift verification. Support explicit runtime source versions 1 and 4; intermediate offline schemas remain unsupported by this runtime until separately selected and verified.

T022 issuer increment: only authenticated durable console POST may issue a handoff. Require canonical console HTTPS Origin/Host and explicit X-Atom-Intent: open-private-content, application/json and bounded strict binding/challenge-only body. Server chooses configured immutable content-host exchange URL with token fragment; never accept return URL, viewer or source session from caller. GET does not issue. No-store/referrer policy protects returned URL; successful issue is not a claim of human action without the pending UI gate.

Consent preparation requirement: authenticated console must fetch authoritative project title, selected immutable release/revision, audience, current-versus-historical status and bootstrap expiry before explicit access action. Query IDs alone are not display authority. Read-only inspection must validate live source, owner, publication and unconsumed bootstrap atomically; it must not create credentials or expose raw nonce/session/handoff secrets.


### Explicit private-content confirmation
The authenticated /content-access page must inspect authoritative stored scope without issuing credentials, display project/release/revision/current-or-historical status and expiry, and issue only on explicit activation. Reject ambiguous query and response destinations outside the inspected pinned HTTPS origin; credentials stay in the exchange fragment and HttpOnly cookies. Pending requests are bounded and obsolete route requests cannot update or navigate a newer page. Uncertain issuance is not automatically retried. Confirmation completion is not full enterprise or embedded-access acceptance.


### Truthful logout outcome
Logout must preserve local identity and show an explicit uncertain/failure outcome unless the server returns the expected success acknowledgement. A network failure, timeout, non-success status (including 401) or malformed success must not be presented as completed revocation. Bound waiting and prevent duplicate clicks; allow explicit retry. A successful durable logout must make an already-installed private-content credential unusable on the next read.


### Unknown authentication state
Initial network/server failure while checking the session must remain an unknown state, not an anonymous-session assertion. Protected and authentication routes show a bounded check or retryable error without losing the requested route. Public content remains readable; session-dependent actions wait for resolution. Later refresh failures preserve the prior identity and work surface while displaying uncertainty. Only authoritative 401 establishes an absent session. Obsolete checks must not overwrite newer sign-in/logout outcomes.


### Issuer shutdown ownership
Console content inspection and issuance must stop admission when main application shutdown starts. Admitted body intake and database work remain owned until actual completion, including a disconnected caller. Bounded drain timeout must propagate shutdown failure without reopening admission or discarding ownership. Restart cannot reset capacity while operations remain unfinished.


### Bounded issuer response delivery
After admission, content-scope and handoff responses, including recognized request/authorization errors, retain ownership until ASGI delivery finishes or fails. Send timeout or cancellation releases delivery ownership without reversing any committed credential. A retry after a committed but lost reply must not issue a duplicate handoff. Shutdown must observe blocked delivery as unfinished work.


### Account-wide self-service revocation
A live durable console session may revoke all currently live console sessions of its own account. The writer transaction rechecks the authenticated source, bounds affected sessions and commits all revocations atomically. Derived content reads and unredeemed handoffs must fail through their source-session checks. Later password-authenticated login is allowed; an old revoked source must not revoke that later session. This operation is not an account lock or password reset.


### Account settings revocation action
Offer account-wide logout only when server user metadata advertises durable-session support. Explain current/other-device and private-access effects, require explicit confirmation, and allow cancellation before mutation. Pending action cannot be submitted twice. Failure stays visible without clearing identity; only acknowledged success navigates away. Capability display is not authorization.


### Durable security audit requirement
Follow contracts/security-audit.md: committed security transitions need atomic, redacted, immutable event records; denial observations remain distinct. Stable identity permits export deduplication and correlation to immutable release evidence without credentials/code. No plain logger call may satisfy durable audit acceptance. All migration/runtime/retention/privacy/export gates are explicit and presently unimplemented.


Audit storage increment: explicit offline v5 defines immutable, typed event records and separate delivery ownership/state. Replacing an existing row must be rejected as well as ordinary mutation; exported state cannot silently regress or disappear. This schema is not enabled for application serving until all exact-version consumers, transactional event writers and their acceptance gates are implemented.


Console audit implementation increment: v5 session creation, single revoke and account-wide revoke must co-commit their typed event in the owning transaction. Single-revoke replay emits no duplicate event. v4 remains the explicit existing non-audited schema; accepting a broken v5 audit insert without rollback is prohibited.


Content audit increment: on v5, successful handoff issuance and content-session redemption each co-commit one typed event with authoritative binding/project/release/revision/generation. Audit failures roll back credential insertion and both consumption markers; read-only scope inspection and replay denial must not fabricate committed events. Credential secrets, challenges and credential digests are excluded.


Release audit increment: explicit v5 publication/unpublication co-commits one authoritative release transition event with pointer/binding/receipt mutations. Receipt replay must not repromote or duplicate audit history. Any failure writing the event preserves the previously published state.


Audit schema runtime compatibility: explicit v5 is now an accepted exact-schema runtime/content target alongside existing supported versions. This does not weaken SQL-definition/journal verification, accept intermediate runtime schemas2/3, auto-migrate a database or imply production rollout readiness.


Audit crash acceptance boundary: abrupt process exit after event insertion but before commit must recover unchanged business/audit state; abrupt exit after commit and before returning must preserve both. This acceptance is distinct from power-loss/filesystem durability and remote export acknowledgement.


Audit read boundary: authenticated account scope is derived from the caller, never another supplied user id. Project scope requires current ownership. Each page rechecks live source and ownership in the same read snapshot as event retrieval. A fixed upper sequence and exclusive after cursor make a bounded scan stable across equal timestamps and new appends. Only explicit event columns are returned, without export credentials/state.


Audit HTTP boundary: GET /api/audit/events requires durable signed console authentication, canonical HTTPS console host and inspect-audit-events intent. An Origin header, when present, must match exactly. Caller account ids are not accepted; project is optional current-owner scope. Continuations with after>0 require an upper watermark. Query length256 bytes, exact unique allowlisted fields, numeric signed64-bit bounds and limit1-100 are enforced. A separate four-slot admission pool owns each request through authentication/query and bounded response delivery; cancellation does not abandon a live worker. Missing schema5 and storage/schema failures return503 without automatic migration or false empty results.


Audit delivery state boundary: only a trusted configured exporter may use the internal repository; it exposes no tenant-facing enrollment API or network call. Retained delivery rows bind one destination id to one account/project scope. Enrollment cannot exceed a batch100 or outstanding cap10000 and explicitly reports remaining source events. Claims bound count100, compact event-array bytes262144 and lease1-300s, atomically increment attempt, and reclaim expired leases. Ack/retry must own every requested event with a currently unexpired lease; an invalid mixed batch changes nothing. Retry delays grow from2s to at most300s. Source audit records remain immutable and separate from delivery state. A network ack, authorized destination configuration and retention policy are still required before complete export acceptance.


Audit destination boundary: operator configuration supplies canonical DNS hostname, absolute restricted path,1-8 approved canonical public IPv4/IPv6 addresses, scope and separate bearer token. Fixed HTTPS443 only. Reject userinfo/query/fragment/control characters, dot-segment paths, private/link-local/loopback/multicast/reserved addresses and IPv6 transition/mapped forms. Direct approved-IP connection must preserve certificate hostname checking and SNI. No runtime DNS lookup or environment proxy is used. Total connect/handshake budget10s, per-address3s with handshake2s; cancelled or failed handshakes close sockets. Token is omitted from object repr and generic errors. This does not itself send events or confirm delivery.


Audit HTTP sender boundary: transmit only1-100 fixed-column same-scope events as compact ASCII JSON, at most262144 bytes, with unique stable event ids. POST uses approved destination TLS connection, explicit Host/Content-Length/type/version/body SHA256 and isolated bearer credential. Receiver contract requires durable deduplicated storage of every event before HTTP204 plus exactly one X-Atom-Audit-Ack matching the sent body SHA256. Any other2xx is not an acknowledgement. No redirect, automatic resend or remote body parsing. Total send deadline15s (validated configurable.01-30s), total incoming response bytes16384, at most4 informational responses, no upgrade or body framing on ack. Cancellation/timeout closes the connection and leaves local acknowledgement to the caller; sender itself never updates delivery state.


Audit exporter lifecycle: each explicitly constructed destination executor admits at most one cycle and owns at most one database executor thread. Cycle enrolls, claims60s, sends with existing15s transport budget, then acknowledges only confirmed events or schedules durable retry. Overall cycle40s; ordinary close45s (validated.01-60) closes admission and wakes scheduler before draining. A cancelled waiting caller does not cancel the owned cycle. If the cycle itself is interrupted during database I/O, admission remains held until the actual thread future completes. Nonretryable receiver rejection closes admission for operator correction without marking delivered. Scheduled runs default every5s and never overlap; pending leases survive interruption for expiry recovery. This is standalone controlled execution, not yet automatically enabled by main settings.


Audit main enablement: export defaults disabled. Process operator ATOM_AUDIT_EXPORT_CONFIG supplies a strict ASCII JSON array of0-4 destinations, at most32768 characters, exact fields/no duplicate keys or destination identities. Session mode must be durable; export tokens must differ from session/runtime/provider/broker credentials. Raw secret-bearing configuration is excluded from settings repr and model dumps. Interval is1-300s (default5); optional CA file must be absolute. Main must verify every configured destination's exact storage/scope before starting any schedule, refuse old/drifted schema without migration, close all admissions before waiting, attempt all exporter drains even if another fails, and never replace an unfinished prior service instance. These are per-process limits, not a cluster-wide concurrency cap.
