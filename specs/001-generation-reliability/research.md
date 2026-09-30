# Research and decisions
- Budget checked only on incoming lines and timeout rewritten to success: use independent deadline and truthful outcomes.
- Cancel bypasses run finalization; startup never reconciles: centralize durable cleanup and startup reconciliation.
- Reads use /workspace while writes use project paths: explicit sandbox environment root; no global symlink or command-string substitution.
- Runtime supports durable session recovery and detects length stop: bounded same-session recovery, not full build replay.
- Flow clicks lack required input; result counts accept duplicates: validated declarative prerequisites and exact coverage.
- Concurrent event sequence writes race: serialize persistence and delivery.
- Spec Kit reference: https://github.com/github/spec-kit/blob/main/docs/reference/core.md . Installed CLI generated bundled Codex skills and scripts.
