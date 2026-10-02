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
