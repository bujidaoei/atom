# Audit destination governance and retention — implementation and remaining design

Reviewed 2026-10-01 against 5a35473. Refines T029/T030 and parent FR-008/FR-011/FR-012. No retention mutation is authorized by merely producing this document, and retention remains design. Current component acceptance is recorded at the end of this contract and in tasks.md.

## Official evidence and limits

- [Atoms project history](https://help.atoms.dev/zh/articles/12129557-project-history) separates restore from creating a separate project and makes database-copy/synchronization choices explicit. Historical preview availability depends on project capabilities. Adopt explicit source/target and resource choices; this review did not exercise paid UI actions.
- [Atoms publishing](https://help.atoms.dev/en/articles/12129577-publish-your-project) requires checking the live result and explains that restoring a project need not reverse production data or external actions. Adopt separately evidenced code, data and external-effect recovery boundaries.
- [GitHub audit streaming](https://docs.github.com/en/enterprise-cloud@latest/admin/monitoring-activity-in-your-enterprise/reviewing-audit-logs-for-your-enterprise/streaming-the-audit-log-for-your-enterprise) documents a finite pause buffer, health checks and receiver-specific age limits. Adopt explicit continuity/gap state and destination-aware recovery; do not copy its numeric policy as Atom's default.
- [GitHub audit API](https://docs.github.com/en/enterprise-cloud@latest/admin/monitoring-activity-in-your-enterprise/reviewing-audit-logs-for-your-enterprise/using-the-audit-log-api-for-your-enterprise) distinguishes ordinary audit retention from Git-event retention. Event class and transport buffer are distinct policies.
- [GitLab audit events](https://docs.gitlab.com/user/compliance/audit_events/) documents indefinite audit-event retention. This is evidence of a different vendor policy, not proof that unbounded local disk growth is safe for Atom.
- [GitLab streaming](https://docs.gitlab.com/user/compliance/audit_event_streaming/) distinguishes owner-controlled deactivate/delete and requires event-id deduplication. Adopt explicit administrative transitions and keep receiver acknowledgements destination-specific.

The direct my-projects URL could not be read by the web fetch tool in this review. No new authenticated Atoms full-flow acceptance, product limitation or paid-plan conclusion is inferred from that fetch failure.

## Current verified gap

Current v5 event/delivery delete triggers prohibit ordinary deletion. Current destination configuration is process-local; terminal receiver errors are also process-local. `collect_status` reports configured destinations only.

Actual SQLite regression evidence demonstrates:

1. Removing destination A from config leaves its leased/unconfirmed rows and source events unchanged, but configured-only status no longer lists A.
2. Re-adding A recovers its retained rows; expired claims rotate ownership and retain event payloads.
3. Replacing A's path with B creates a different destination identity. B's complete acknowledgement does not settle A's outstanding obligation. Both delivery histories coexist.
4. Token/IP rotation for the same logical receiver retains destination identity.

Therefore a cleanup planner cannot infer historical delivery obligations from the current environment configuration or `--require-drained` alone. No delete implementation will bypass v5 triggers or relabel pending events as delivered.

## Next schema and governance decisions

Use a new explicit offline migration; keep v1-v5 SQL definitions and journal hashes unchanged. Extend exact-schema consumers and startup checks before selecting the new version. Back up and prove migration rollback/reopen/restore separately.

Persist a destination registry containing stable destination id, scope, configuration generation, lifecycle state, creation/change timestamps and fixed terminal reason where applicable. Do not persist bearer values, their digests, arbitrary errors or request payloads. Runtime endpoint and credentials remain protected operator configuration. Existing delivery identities must be discovered even if missing from current config; infer scope from existing event references, reject conflicting historical scopes and mark unconfigured identities visibly.

Administrative operations must distinguish register, suspend new claims, resume, block on permanent rejection and retire. Omission from process config cannot retire a destination or discharge its pending work. Generation-checked command receipts make repeated administrative requests idempotent and reject changed-payload reuse. Stale worker failures cannot overwrite a newer configuration generation. A pause stops new claims; already admitted sends have explicitly draining/unknown states until their outcome or lease recovery is established. Do not promise retroactive cancellation of remote effects.

Restart must preserve blocked state until an explicit authorized resume/configuration action is recorded. Status must distinguish registry-wide obligations from the active process configuration. Existing source-scope authorization stays required for tenant-visible information; operator registry access is not implicitly granted to ordinary project members.

## Retention and archival contract

No arbitrary default expiration is selected by this research. An operator policy must state scope/event classes, age boundary, required destination set and generation, archive destination/trust, legal/operational holds where configured, and treatment of retired receivers. Retention is not enabled until those inputs and storage/restore capacity are validated.

Planning is read-only and captures a fixed sequence upper bound plus policy/configuration generations. It enumerates eligible and blocked events, including never-enrolled and removed-destination work. It produces a plan digest and counts; a current zero backlog alone is not a deletion permit.

Archive in bounded immutable chunks, retaining original event ids/sequences and typed payloads. Reuse existing count/byte ceilings as initial implementation bounds, then measure actual workloads. A manifest binds scope, policy generation, source sequence interval, counts, content digests and verification result. Treat network acknowledgement, archive existence and independently verified recoverability as separate evidence.

Pruning requires an explicit authorized plan and durable receipt, verified archive, expired policy age, no hold and satisfied historical delivery obligations. Recheck all mutable gates in the owning transaction; a changed policy/destination/hold invalidates the plan. Bound each deletion batch and retain a durable retention watermark/manifest reference so paginated readers can report missing/archived ranges instead of silently returning a complete-looking result. Duplicate commands and crashes must not erase manifest/receipt evidence or advance the watermark ahead of deletion.

No automatic discard of unconfirmed events, implicit retirement, source-event mutation or disabling immutable triggers at runtime. The new schema must define the maintenance authority deliberately and remain exact-schema verified. Database-administrator tampering is outside the protection offered by ordinary SQLite triggers.

Capacity admission and emergency operations require separate drills. Artifact growth must not silently consume the audit recovery reserve; disk exhaustion must not be presented as successful revocation or successful logging. Numeric thresholds need measured deployment storage and recovery evidence.

## Atom product distinction

Extend the existing revision/verification/publication evidence chain with a recovery manifest. It identifies the selected source and current revision, schema version, data recovery point, publication generation, unresolved external actions and audit coverage interval. A restore result reports each dimension independently and links its actual verification evidence. An unavailable historical preview or incomplete data recovery cannot become a green overall recovery claim. This is a proposed user capability, not a delivered screen or achieved RPO/RTO.

## Required acceptance before closure

1. Migration preserves all existing delivery identities, including removed config; conflicting historical scopes fail without partial schema changes.
2. Register/suspend/resume/retire and permanent-error races respect generation/receipts across restart and competing workers.
3. A removed or blocked destination's unpaid delivery obligation remains visible and blocks retention unless an explicit policy action resolves it with retained evidence.
4. Mixed destinations, never-enrolled rows, newly changed holds/policy and concurrent append cannot produce an unsafe plan or prune.
5. Corrupt/missing archive, false receiver ack, partial local write and process exit leave source and recovery metadata consistent.
6. Independent restore of an archive reproduces exact event dictionaries and exposes deliberate retention gaps to API/UI pagination.
7. Full backend/runtime/content/browser compatibility, real capacity/backup/restore and production egress checks remain separate gates.


## Implementation boundary
T031 partial increment: explicit offline schema6 registry migration preserves historical destination scopes, rejects mixed scope, and adds generation/state and active-scope delivery guards. 99 focused migration/delivery/configuration tests pass. Authentication, content, publication, revision and audit-read consumers now accept exact schema6 and retain transactional audit writes. Export delivery remains exact5 pending governance integration; do not upgrade serving databases yet. Administration/retention and complete T031-T034 acceptance remain open. The administrative and retention portions above remain design. v1-v5 migration definitions and hashes remain unchanged.


## T032 implementation decision: durable administrative receipts
Keep committed schema6 definitions immutable. An explicit offline schema7 adds an append-only typed administrative receipt ledger; ordinary business/export consumers remain fail-closed until separately verified for7. Trusted local operator commands require a bounded command id, operator identity, destination id/scope and expected generation. Receipt identity is global command id; exact replay returns the original typed outcome even after later changes, while changed-payload reuse is rejected. No token, endpoint, credential digest or free-form text enters receipts.
Register creates an active destination at generation1 only with expected_generation0. Resume permits unconfigured/paused/blocked; suspend permits active; block permits active and a fixed reason. Retire permits any nonretired state only when every committed scoped event is already delivered to that destination, including never-enrolled events; it captures the scoped sequence watermark. No active lease is relabelled delivered. Every transition increments generation, with nondecreasing timestamp, and writes its immutable receipt atomically. Worker block uses its captured generation so a stale failure cannot undo an operator resume. The operator identity is supplied by trusted process authority, not a tenant request.


T031/T032 foundation increment: explicit offline schema7 adds immutable typed destination command receipts without changing v1-v6 definitions/hashes. Trusted operator repository and app.audit_admin implement register/suspend/resume/block/retire with expected generation, exact replay and atomic registry/receipt commit. Retirement rejects every unconfirmed scoped event, including never-enrolled rows.111 focused tests pass. Ordinary business/runtime/export consumers still refuse7; full integration, operational backlog coverage and T031-T034 acceptance remain open. No serving database upgrade authorized by this component evidence. Administrative receipts are local immutable evidence; their export and tenant-facing inspection are not implemented.


T031/T032 governed delivery increment: delivery repository and standalone exporter now support exact schema7 alongside5 (6 remains unsupported for export). Explicitly registered matching scopes are required; only active destinations enroll/claim, and claims capture generation. In-flight valid leases may still settle after suspend. Permanent failure persists a generation-fenced block receipt; stale failures return superseded and never overwrite newer administration. Restart preserves inactive state until explicit resume.115 focused tests pass. Main/business consumers still lack7 compatibility, registry-wide backlog reporting and full acceptance remain open; do not upgrade serving databases. Standalone realTLS evidence covers lost ack and403/restart/explicit-resume recovery, not whole-main7 deployment.


Current schema7 compatibility (supersedes earlier not-yet-compatible notes): authentication, content capabilities, revision/verification/publication, audit reads and governed export now accept their explicit verified schema7. Main plus actual TLS verifies lost acknowledgement and permanent rejection across restart; explicit operator registration/resume remains required.28 main/TLS/service checks and529 business/HTTP/revision checks pass. Global historical backlog reporting, full browser/production/retention gates remain open; this is not rollout approval.


T032 operational visibility increment: audit_admin status now reads every registered historical obligation in one exact7 read-only snapshot, independently of process configuration. A bounded keyset detail page includes never-enrolled/pending/leased/delivered/expired counts and timestamps, while registered_drained is checked over the entire registry, not the page. Empty registry is not drained.64 focused tests pass. Scope is explicitly registered_destinations, not all possible unregistered business scopes or proof of active transport; retention/deployment/full-task gates remain open.


T031/T032 are accepted at component scope: versioned governance schema and exact consumer compatibility, durable generation-fenced administration and registry-wide obligation inspection. Actual Chromium5/7 private content/auth/revocation checks supplement prior migration/crash/TLS/runtime evidence. This does not close retention, denial observation, trusted verifier, live model or enterprise production acceptance.
