# Workspace Read Contract
GET /projects/{id} retains ownership/error behavior and adds nonnegative project.eventSeq.
Catalog reads validate exact schema/journal. Empty workspace stays empty; corrupt artifact stays failure. Manifest reuse ends with response.
Stream timeline consumes valid increasing events. Only updates beyond snapshot eventSeq invalidate full detail. Initial stream-open does not independently refetch; reconnect reconciles state.
Concurrent refreshes become one active plus one trailing read. Callers may await freshness, but first success applies before trailing work. Unmount aborts and clears pending work. Fifteen-second timeout is retryable; mutation idempotency unchanged.
