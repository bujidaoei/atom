# Verification plan
Run grant tests with existing backend pytest and synthetic independent signing keys. Reject wrong algorithm/signature/purpose/schema/time/scope, missing/extra fields and oversized tokens; verify boundary seconds and maximum lifetime.
Subsequent stages require actual SQLite reopen/concurrent create/revoke tests, Docker create-response loss/cancel/TTL/daemon outage, controlled file tools via HTTP, exact snapshot/fence tests and Pi recovery. Child 006/007 results are prerequisites, not substitutes. Record failures and unexecuted gates in evidence.md.
