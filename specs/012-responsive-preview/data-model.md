# Data model

Reuse schema18 preview_handoffs, preview_sessions and preview_audit_events. View ID is the existing purpose-separated handoff hash; it is a public selector, not authorization. Raw session secret is HttpOnly and only its hash persists.

Grant: pending -> consumed/expired. Session: active -> expired/revoked; source logout and project deletion deny reads. Replacement requires the exact current owner/source session.

UI: empty -> acquiring -> loading -> displayed/failed. Async work is fenced by project/revision/request generation. Viewport selection is independent of iframe lifetime. Refresh uses trusted resume; retry/new revision requests fresh access.
