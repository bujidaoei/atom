# Data Model
- Existing acceptance_runs timestamps represent UTC even when SQLite returns naive datetime objects; normalize at read/comparison, preserve stored values.
- Immutable saved revision and artifact remain the content authority.
- Publication snapshot references a retained revision, creator, timestamp, previous publication and an explicit check policy/state; absence of functional evidence must not be encoded as passing evidence.
- Live publication has monotonic generation, live flag, stable sharing address and selected snapshot.
- Each snapshot retains its committed publication generation, unique per project; history uses that number for order and pagination even when wall-clock timestamps tie or move backward. Migration derives existing values from durable command receipts, never random-ID ordering.
- Restore is a new durable event selecting historical content, not mutation of history or editing draft.
- Precise policy/schema migration is reviewed under T004 before publication implementation.

## Schema16 policy fields
release_records.verification_mode is advisory|required, defaults to required for existing rows. Verification identity and two verifier digests are nullable together; advisory stores NULL, required stores exact existing evidence. Direct revision/project/workspace relationship remains enforced independently of evidence. Rollback provenance preserves source/displaced/new IDs and monotonic generation, using NULL-safe comparisons. Existing immutable artifacts and bindings are retained; no separate ordinary-publication table or mutable-files bypass.

## Planned IP-only origin ledger (not implemented)
The next additive schema introduces one immutable reservation row per `(project_id, purpose)` where purpose is `preview` or `public`. A single global `UNIQUE(port)` constraint spans both purposes and every project; `UNIQUE(project_id,purpose)` prevents reassignment of a project's role. A reservation is never deleted or updated, including after project deletion. Inserts require a real project at the time of reservation but cannot use a cascading foreign key because the port must remain unavailable forever even if the project is removed. Two roles are reserved in one transaction, with a bounded configured pool and deterministic exhaustion error. The application never infers ownership from a port alone: it first resolves the immutable reservation, then checks project existence, requested role, owner capability for preview, and current public release for public content. Old per-release binding IDs remain evidence for legacy link continuity, not the stable browser origin. Ingress renders listeners only for extant eligible projects while keeping retired ports reserved in the ledger.

No fixed port numbers or pool size belong in the schema; deployment configuration and Tencent Cloud ingress/firewall must agree on the capacity. A failed Caddy reload or TLS probe must not advance the public release pointer. Restart reconciliation computes desired listeners from the authoritative ledger and records failure without reassigning a port. This contract is pending migration, repository, browser and production tests under T012a5.
