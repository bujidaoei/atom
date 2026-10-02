# Data model

No schema changes. Existing `AcceptanceRun.created_at` and `Run.started_at` represent UTC instants; database reads may be timezone-naive. The API exposes an explicit UTC offset in `acceptance.createdAt`. Stored check history remains unchanged when newer generation makes it stale.
