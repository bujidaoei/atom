# CR-001 generation repair

Confirmed cause: two overwrite writes split one file; the second2977-byte tail replaced the first5187-byte prefix. Concatenating the actual two recorded chunks in a disposable server directory passes real Node syntax checking (SHA256 df2e5f7c2112054c1cb76ac81ee4e2d6f9cea11fc19a7d7a15e72423d3b79fe3). No production file or head was changed by that experiment.

Use typed ArtifactValidationError for deterministic missing entry/resource and parser errors. User diagnostic contains relative path, line and bounded reason; no temporary path, stack or runtime version. Node availability/process failures remain infrastructure failures and must not trigger model repair.

Shared generation helper drives build/revise/race with configured maximum2 repair turns (valid0–3). All turns share original total budget. Each turn gets remaining time, creates a separate auditable Run, charges actual usage once and in broker mode starts from committed current revision. Preserve original contract/context and give the exact diagnostic; instruct read affected file and edit or write a complete replacement. Only typed validation failure is eligible. Cancellation, timeout, exhausted budget, provider failure, quota and unconfirmed broker cleanup never start another repair.

Intermediate failed model completion prose is replaced with an honest platform validation message. Emit persisted repair progress; only final validation success yields ready. Failed snapshots remain actual revisions, never falsely described as unsaved. Aggregate all per-turn usage in race stats, including cancellation. Tests use scripted runtimes for fault injection and actual Node/files/DB; live provider/browser acceptance is separately required.
