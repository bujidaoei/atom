# T034 bounded audit pruning contract

Status: design only, 2026-10-01. T033/T035 are accepted components. No prune command, schema11 migration or reader-gap implementation exists yet. Existing delete guards remain active.

## Evidence and decisions

Current `security_audit_delivery.event_id` references the immutable event table. Deleting only parent events cannot work with foreign keys enabled; deleting children without proof would erase delivery obligations. SQLite documents per-connection foreign-key enforcement and parent/child deletion constraints ([official documentation](https://www.sqlite.org/foreignkeys.html)). Keep foreign_keys enabled; never disable it for maintenance.

Current events use INTEGER PRIMARY KEY AUTOINCREMENT. SQLite prevents reuse of previously committed automatically generated rowids but does not promise consecutive values ([official documentation](https://www.sqlite.org/autoinc.html)). Therefore max(sequence) alone is neither completeness evidence nor a sufficient retention watermark. Preserve sqlite_sequence and retained identity tombstones; explicit manual identity reuse must also be rejected.

SQLite triggers support aborting invalid mutations; connection-local TEMP triggers are not a global protection boundary ([official documentation](https://www.sqlite.org/lang_createtrigger.html)). Use persistent guards in a new explicit migration, with narrowly scoped maintenance authority available only to the owning connection. Do not drop guards during live maintenance or authorize deletion merely by inserting an intent row. The implementation must prove absent authority fails closed and cannot leak to ordinary serving connections. A connection-local fixed membership function is the selected approach to prototype and test, not an already proven guarantee. Privileged database-file administrators remain outside this boundary.

## Command and transaction

Trusted operator supplies command ID, operator ID, archive ID, isolated recovery ID and expected policy generation/context. No tenant HTTP mutation or automatic TTL loop. Limit one command to the exact original archive chunk (at most100 events/262144 bytes). No arbitrary range deletion.

Before the source write transaction, read committed archive bytes using the immutable ledger digest, validate all original fields and metadata, and require an existing schema10 isolated recovery receipt bound to the same archive and approved verifier configuration. Missing/corrupt objects, legacy recovery receipts or absent verification reject the command. No remote work occurs while holding the source write transaction. Holding verified bytes is not a promise of future storage availability; immutable protected archive retention remains an operational prerequisite.

Inside one bounded BEGIN IMMEDIATE transaction:

1. Verify exact new schema and migration hashes; resolve exact command replay or reject changed identity/configuration.
2. Recheck unchanged immutable archive/recovery anchors, current policy generation/context, active state, minimum age, absence of every active hold and complete registered destination set including retired cutoffs.
3. Compare all original typed event dictionaries against the verified archive bytes; require every applicable receiver obligation settled and no pending/leased delivery for any selected event. Refuse ambiguous partial prior deletion.
4. Install only the exact selected event identities in connection-local maintenance authority. Record an immutable command receipt and individual typed archived-event markers with original sequence/event identity, scope/class, archive/recovery reference and command ID. Markers must not depend by FK on rows about to be removed.
5. Delete only delivered child rows for those events, then selected source events. Assert exact affected counts. Commit receipt, markers and deletions atomically. Clear connection authority in finally and close the connection on every path.

Rollback or process death before commit leaves all source rows and no receipt/markers. Post-commit response loss resolves to the exact immutable receipt by command ID. A different command cannot reinterpret the same event identities or create conflicting markers. Events, archives, verification receipts and administrative history remain immutable; only the explicit new maintenance path can remove eligible event/delivery rows.

## Pagination and application behavior

Extend the audited page contract before enabling the new schema for serving. Compute fixed upper from both live events and archived markers in the authorized scope. Fetch one bounded sequence-ordered union, with original live event dictionaries and separately typed archived markers; total records, not each category independently, count toward the100-record limit. next_after is the last emitted union sequence only when another union record exists. A page containing only archived markers is not an empty history or end-of-stream.

Return archived markers separately from live event payloads so they cannot be mistaken for reconstructed business events. The UI must explicitly show that records are archived, their covered identities/range and recoverability reference without exposing server filesystem paths or credentials. Do not collapse noncontiguous or differently scoped/classed markers into a complete-looking interval. Authorization and revocation checks apply before both live and archived reads. Publishing newer events must never reuse retained sequence/event identities.

## Required implementation and acceptance order

1. New offline migration: immutable prune receipts/markers, guarded identity reuse and persistent deletion guards. Preserve all frozen migrations; verify backup/rollback/reopen and refuse unsupported serving versions.
2. Owner-only bounded prune service and CLI; no defaults or in-process legacy recovery authority. Implement exact replay and revalidation races.
3. Reader/API/UI union pagination and explicit archived state; then exact consumer/runtime/browser compatibility.
4. Actual archive/store/broker-backed tests: successful prune, holds/policy/new receiver/retirement changes, active delivery lease, missing/corrupt object, wrong verifier, duplicate/mismatched command, source payload mismatch and partial archive coverage.
5. Actual child death immediately before/after commit and real source ENOSPC, with full source/receipt/marker checks. Test direct deletes and identity reuse from ordinary connections remain denied, including after owner exception/cancellation.
6. Deployment backup/restore, measured storage reserve and operational review before any production prune. Component tests cannot close these gates.

T034 remains unchecked until its complete implementation and explicit acceptance are proven. This contract does not authorize executing deletion now.


T034.1 offline schema11 foundation (2026-10-01): explicit migration adds immutable prune receipts and per-event archived markers, exact archive/isolated-recovery/policy anchoring, bounded count checks, alternate-key replacement guards and archived sequence/event-ID reuse rejection. Persistent event/delivery delete guards require matching markers plus connection-local atom_prune_authorized(command_id,event_id,sequence); absent/false authority fails closed, pending/leased deliveries cannot be removed, and remaining delivery children prevent parent deletion. No maintenance service installs this function in production.55 schema/guard/migration/legacy-schema10 tests pass (9.394s, no failures/errors/skips), including source versions0..10 backup/replay, late rollback, actual pre/post migration-COMMIT death and ordinary connection denial. Frozen migrations1..10 unchanged. Serving and retention/archive owner still reject11. These are synthetic schema constraint tests, not real authorized prune acceptance. T034 and its subtasks remain unchecked pending full owner/reader/race/deployment implementation; T033/T035 remain accepted. No production migration/push/deployment.

Schema11 authority contract: receipt insertion requires the connection callback to approve (command_id,'',0); marker insertion and event/delivery deletion require the exact (command_id,event_id,sequence) membership. Callback is not provided by SQL schema or default serving connections. Ordinary raw SQL lacking the function fails, even with persisted markers. The future owner must create the callback only after full gate validation, clear it in finally, and assert exact marker/deletion counts before commit. Schema alone cannot prove archive IO, destination completeness or complete chunk deletion; these remain owner obligations and must not be claimed from synthetic SQL tests. Whole-table metadata maintenance remains forbidden.


T034 bounded owner increment (2026-10-01): AuditPruning implements an explicit local schema11-only maintenance operation for one complete archived chunk. It reads committed bytes by ledger digest, validates every manifest field and the full isolated-response digest against configured verifier/image/policy, then rechecks current policy/context/age/holds/destination obligations and exact typed source rows in one bounded transaction. All delivery rows must be settled and bounded. Exact connection membership permits immutable receipt/marker insertion and child-then-parent deletion; exact counts are asserted and callback authority is cleared in finally before commit. Command replay binds full request/configuration and reports historical outcome without claiming current archive availability.7 actual Linux store/network/broker/worker integration cases pass (27.299s), including successful scope-preserving deletion, replay/conflict, hold/corruption/wrong verifier/missing receipt denial and injected failure after actual SQL deletion rolling back the complete database. Shared repository/schema regression also passes. No CLI or gap-aware reader/UI is implemented; serving remains exact10 and refuses11. T034 and subtasks remain unchecked, T033/T035 remain accepted. No production prune/migration/push/deployment.

The owner uses a dedicated RetentionRepository subclass restricted to11; ordinary retention/archive interfaces remain8/9/10. Shared archive-to-ledger validation is extracted as a pure helper. New pruning never treats historical in-process recovery as evidence. No callback or SQL write is installed until full preflight passes. Complete receipt/marker/deletion atomicity is enforced by the owner transaction; schema-only synthetic callbacks are not the product authority path.
