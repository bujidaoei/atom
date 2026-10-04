# Data Model
No persistent migration. Project snapshot adds existing eventSeq as a lower-bound invalidation watermark, not authorization or delivery acknowledgment. Historic events still render.
Catalog state is an owner-checked WorkspaceRevision plus incompleteRevisionId captured in one SQLite read transaction. Incomplete status derives from the selected head and confirmed receipt.
Verified manifest map exists per HTTP request only, keyed by artifact(key,revision,size). No failed manifest enters it; every workspace separately rechecks ownership/head.
Refresh states: idle -> reading -> idle; reading+pending -> apply -> reading. Disposal aborts and prevents late callbacks; failures release slot, background errors preserve displayed content.
