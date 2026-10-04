# Research
Baseline: origin/main d2c889b; isolated worktree because original codex/008-sandbox-broker is stale and dirty.
## Decisions
1. Approval note currently appears only in _build_prompt, never requirements or messages; old _squad_context includes every historical role message. Replace note-on-build with refinement and authoritative snapshot context.
2. _plan currently applies Emma before Bob succeeds. Delay contract publication until all planning succeeds. Failure must preserve previous head.
3. Use additive migration v19 and SQLite transactions, not files/messages as an implicit database. Existing strict schema consumers must explicitly admit compatible v19; historical migration hashes stay unchanged.
4. Reuse ReleaseTab history card/list controls through one generic HistoryList; contract data differs from immutable code artifacts, so storage remains separate.
5. Snapshot restores append a new version. No destructive pointer rewind or revision/artifact mutation. Expected-head validation prevents stale tabs.
6. Existing Emma system prompt caps at 3–4 requirements and parser truncates at 8; refinement needs strict full-document validation and preservation, using the existing verifier codec bounds.
7. Deployment uses protected paired backup/candidate workflow. Source v18 backup stays immutable; only candidate migrates to19. No credentials in artifacts.
## Alternatives
Appending prose to existing requirement is insufficient: exclusions/checks/architecture remain inconsistent. Re-running whole Mike/Iris pipeline is unnecessary for scoped refinement; Emma and Bob update the full contract from current state.
