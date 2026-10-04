# Contract APIs
Owner authentication applies to every route; responses no-store.
GET /api/projects/{id}/contracts?before={version}: currentId, items metadata (max20), nextCursor.
GET /api/projects/{id}/contracts/{snapshotId}: full snapshot; inaccessible is404.
POST /api/projects/{id}/contracts/refine: message (trimmed1..4000), expectedVersion (snapshot ID); Idempotency-Key. Returns runId; 409 stale/busy, 422 invalid.
POST /api/projects/{id}/contracts/{snapshotId}/restore: expectedVersion; Idempotency-Key. Returns snapshot; appends and changes project to awaiting_approval atomically.
POST /api/projects/{id}/approve: expectedVersion; nonempty note rejected with actionable error. Returns runId bound to snapshot.
Project detail adds contractVersion and current full contract. Planning/refinement SSE completion triggers canonical reload. Legacy project baseline is created transactionally before first versioned mutation; read does not fabricate earlier history.

