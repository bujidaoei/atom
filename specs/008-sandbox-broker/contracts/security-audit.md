# Security audit contract — incremental implementation; export pending

Reviewed 2026-10-01 against baseline f8d9857. This contract refines T022 and parent enterprise security requirements. It adds no claim that current diagnostic logging is durable auditing.

## Official evidence and product decisions
- [Cursor compliance and monitoring](https://cursor.com/docs/enterprise/compliance-and-monitoring): security/administrative events are distinct from usage OpenTelemetry; agent responses/generated code are excluded from audit logs. Adopt separation and metadata minimization, not its specific product event catalog.
- [GitHub enterprise streaming](https://docs.github.com/en/enterprise-cloud@latest/admin/monitoring-activity-in-your-enterprise/reviewing-audit-logs-for-your-enterprise/streaming-the-audit-log-for-your-enterprise): at-least-once delivery permits duplicates; paused streaming has a finite recovery buffer and destination-specific acceptance limits. Adopt explicit delivery identity, backlog health and retention contracts; do not imply unlimited recovery or copy vendor retention numbers as Atom defaults.
- [GitLab audit streaming](https://docs.gitlab.com/user/compliance/audit_event_streaming/): structured JSON events can repeat and consumers deduplicate by event id; exported payloads may contain sensitive data. Adopt stable id and explicit export destination trust, with stronger default payload minimization.

The following is Atom's design, not a claim about vendor internals: committed security transitions and their audit row share the same database transaction. External export is an independently retried outbox. A receiver outage cannot cause credential revocation to roll back after local commit. Local inability to commit the audit row must fail the entire mutation with no false success, matching existing durable mutation failure semantics. Availability and disk-capacity admission must be tested before production selection.

## Event boundary
Initial committed event kinds: console.session.created, console.session.revoked, console.account_sessions.revoked, content.handoff.issued, content.session.created, release.published, release.unpublished. Event kinds are a versioned allowlist. A single account-wide revocation emits one event with affected count in the same transaction, not independently committed per-session events. Replayed no-op operations do not manufacture new committed transition events.

Envelope: event_id, schema_version, event_kind, occurred_at, actor_kind, actor_id when authenticated, scope_kind/scope_id, operation_id where a durable receipt exists, and an allowlisted typed payload. Payload may contain internal non-bearer source-session id, binding/release/revision ids, publication generation and affected count where applicable. None is accepted as authority by an endpoint. A separate monotonically ordered storage sequence supports stable pagination; event_id is export deduplication identity. Retain both, never use wall-clock time alone as a cursor.

Never serialize arbitrary request headers, Cookie, JWT, nonce, challenge, handoff/session secrets, their credential digests, passwords, provider keys, authorization URLs/fragments, request bodies, generated code, prompts, exception messages or arbitrary metadata blobs. Do not default to storing email, IP address or user agent. Export policy and role checks must explicitly govern identity fields; audit capability cannot grant tenant-crossing reads.

Denied access and failed attempts are separate security observations, not committed business transitions. An authenticated cross-project denial must produce a redacted security observation when its bounded sink is available. Unauthenticated events cannot claim a verified actor. They need bounded rate/capacity, fixed reason codes and explicit gap/overflow accounting; observing an unavailable database cannot depend on that same database successfully recording failure. Operational diagnostics remain a distinct channel and must never falsely report that an unavailable durable sink recorded an event.

## Storage and lifecycle
Proposed next explicit offline schema migration: append-only security audit table, stable event uniqueness/indexes, and independently mutable export state. Do not change v1-v4 DDL/hash history. Audit rows reject ordinary update/delete; retention requires a separately authorized, bounded maintenance path with explicit retention policy and gap/watermark semantics. Do not silently cascade deletion from user/project/session into audit history; retained identifiers must not require those entities to remain live forever.

All repositories that verify exact schema versions and both main/content service startup must be updated and tested together before selecting the new schema. A migration-only test does not prove runtime compatibility. Back up, verify source definitions, test mid-DDL/process-exit recovery and restore before rollout. No startup auto-migration.

Export: at-least-once with immutable event_id, bounded batches/payload bytes, finite connect/read/deadline, lease ownership and retry backoff. Ack advances durable export state only after receiver acknowledgement; timeout/lost ack permits duplicate delivery. Event ledger remains independent of delivery state. Explicitly expose backlog size/oldest age, last durable ack and terminal configuration errors. No HTTP call inside the business transaction. Destination validation/credential isolation/SSRF policy and authorization precede enabling export. Retention/backlog limits must never silently erase unsent events or imply all events were delivered.

## Atom differentiation
Connect actor and operation to immutable revision, verification report, publication generation, content grant and later revocation through typed internal references. An operator should be able to explain which verified artifact was authorized and why later access stopped without collecting code or bearer material. This extends the existing evidence-driven release design; it is not yet a working audit explorer or a tamper-proof compliance certification. Local append-only rules cannot defeat a privileged database administrator; off-host retention/integrity verification needs separate acceptance.

## Required acceptance before claiming completion
1. Real SQLite transaction failure before/after audit insert leaves neither partial mutation nor fabricated event; crash/reopen preserves a committed pair.
2. Concurrent/replayed commands produce exactly the actual transition count and preserve stable event ids; account-wide revoke remains atomic.
3. Seed distinct sentinel secrets in every transport field and scan database, event export, logs and exception output; no forbidden value/digest leaks.
4. Tenant/role matrix denies cross-account audit reads; event references never become credentials; stable pagination survives equal timestamps and concurrent append.
5. Slow/unavailable receiver, duplicate delivery, lost ack, worker crash and restart preserve backlog and correctly deduplicate at receiver; bounded shutdown retains unfinished ownership.
6. Capacity/retention/observation-overflow drills distinguish recorded, pending, rejected and missing evidence. No silent success or unbounded memory/disk growth.
7. All affected repositories/main runtime/content/browser paths pass on the new schema; immutable Pi remains unchanged. Production backup/restore and export destination checks stay independent gates.



### Implemented reader component
AuditRepository.page is an internal trusted-caller API (session id is not a bearer). It rechecks source within a read-only snapshot, derives own-account scope or checks current project ownership, and returns fixed-column events with upper/next_after. Bounds:1-100 events, integer signed64-bit nonnegative cursors, SQLite lock3s/progress5s. Retain upper from first page for a stable scan; authorization is independent of cursor input. No HTTP endpoint, generalized enterprise roles or export added in this component.


### Implemented HTTP reader component
GET /api/audit/events now uses signed durable console cookies and inspect-audit-events intent, canonical HTTPS host and optional exact Origin. Query keys project/after/upper/limit only, no duplicates, at most256 encoded bytes; nonnegative signed64-bit cursors, limit1-100, upper required for after>0 and upper>=after. Response: events (fixed ledger columns), upper, nextAfter (null at end). Scope is account caller or currently owned project; no role administration is implied. Missing schema5 returns503; deployment selects migration offline. Reads have a separate four-request pool, owned thread completion and10s response delivery, no-store/no-referrer, bounded15s shutdown drain. Query errors400, host/intent403, credentials401, hidden scope404, unavailable503. UI/export remain pending.


### T029 delivery-state implementation (component tested; export pending)
Add an internal trusted-operator AuditDeliveryRepository on exact schema5; it is not an authorization API or enabled network exporter. A destination id becomes scope-bound by its retained delivery rows; every enrollment/claim/ack/retry/status transaction rejects another scope for that destination. Enrollment scans committed events in that scope with a bounded batch and outstanding-row cap, reports remaining unenrolled work, and never changes source events. Claims allocate fresh random lease ownership, increment attempt atomically, reclaim expired leases, and cap event count/serialized payload. Ack/retry require all supplied event ids to remain owned by an unexpired lease; stale/mixed batches roll back. Retry uses bounded exponential delay. No remote I/O occurs in the transaction. Prove races, replay, expiry, reopen and fault rollback using real persisted events. Destination credentials/URL/authorization, scheduling, actual receiver acknowledgement and retention remain separately required before enabling export.


### Implemented destination and TLS boundary
Initial export receiver contract is operator-selected canonical host/path on HTTPS443 and explicit public IP pins, not arbitrary URLs or runtime DNS. IP changes require a configuration update; credentials/IPs rotate without resetting destination delivery identity, while scope or logical receiver changes yield a new identity. TLS uses approved numeric socket plus original host SNI/certificate verification, no proxy,10s overall and3s/address (2s handshake) bounds. No credential/event bytes are sent by the connection primitive. Standard stream ownership passes to a future bounded HTTP sender; failure/cancel closes socket. Actual sender must still prohibit redirects, define receiver durable ack, redact diagnostics and integrate leases/lifecycle. Production egress policy and authorized configuration remain separate requirements.
