# Revision-bound acceptance and release

Status: design only, not implemented or accepted. Source baseline e7c4bd3, reviewed 2026-10-01. Scope: committed static artifacts in broker mode. Executable deployment, database recovery and external effects require separate contracts.

## Verified source gaps

- routers/publish.py checks ready and legacy index.html, copies a mutable directory, then commits Publication. It records neither revision nor acceptance. Filesystem changes and database commit are separate effects.
- routers/projects.py adopts a heat by copying its legacy directory and updating winner/status; the registered main head is unchanged.
- record_acceptance validates coverage but accepts client booleans without revision, contract digest or trusted verifier identity.
- serialize.acceptance_json compares timestamps with Run start time. Head adoption, contract changes and an old loaded iframe are not captured reliably.
- frontend/src/pages/Workspace.tsx tests the currently loaded same-origin iframe without capturing its revision. Draft asset requests resolve current head independently; published routes read mutable directories.

These are source findings, not demonstrated production incidents.

## Identity and authority

Capture separate immutable identities for artifact revision, requirement contract, verification execution and release. The versioned canonical contract includes ordered checks, setup and expected values. A changed contract invalidates current evidence even if artifact bytes are unchanged.

A verification execution captures owner/project/workspace/revision, artifact digests, contract digest, runner/policy versions, initiator, environment and deadline before testing. A trusted isolated verifier reads the pinned artifact. Ordinary browser reports remain client-reported and cannot authorize enterprise publication. Only scoped verifier credentials may register trusted results for the captured execution; generated pass claims and ready status are insufficient.

A release records exact revision, trusted successful verification, contract/policy identity, audience, creator, previous release and serving descriptor. The public address points to a release ID. Insert release, advance pointer and record audit event in one transaction. Failed commits preserve the previous release. Live releases and retained rollback targets pin their artifacts against deletion.

## Operations

1. Start verification after ownership, artifact and contract validation; capture identities and enqueue bounded execution. Later head changes do not retarget it.
2. Complete verification after checking verifier authority, identity and complete unique coverage. Exact duplicate is idempotent; conflicting replay fails. Stale evidence remains historical.
3. Adopt a heat only with exact source revision, expected main head and no active/unknown main attempt. Verify artifact, then atomically create a main revision referencing it, advance the fenced head and record winner/provenance. No directory copy; no partial winner update on conflict.
4. Publish with expected revision, publication generation and trusted matching evidence under current policy. Recheck scope/identity in the write transaction. Idempotency binds the entire request digest. Concurrent edits conflict instead of silently changing the release candidate.
5. Serve each page and dependent asset from a pinned release. Check current visibility on pinned URLs so unpublish cannot be bypassed. Isolate generated content from control-plane origins/cookies. Verifier access has separate scoped authority; control UI same-origin DOM access is not a trust boundary.
6. Unpublish atomically disables the pointer and records an event; retain history according to policy.
7. Rollback creates a new release referencing an available prior artifact after policy/audience checks. It does not rewrite history or imply database/configuration restoration. Store configuration references, never secret values, in audit records.

Static releases have no runtime-secret selection. Future executable deployment must explicitly add configuration and data-compatibility gates. Retention must expose recoverable targets; no competitor retention number is adopted.

## Migration

Use additive versioned migration with the existing offline backup/verification runner. Do not change the baseline fingerprint or use ORM create_all to bypass migration. Preserve legacy acceptance/publication rows as unverified history without invented revision links. With writers stopped, import published bytes separately from draft bytes: they may differ. Retain original files and rehearse restore before live cutover. Migration cannot convert old browser reports into trusted acceptance.

## Implementation and acceptance order

1. Add schema with real baseline/v1 upgrade, drift rejection, backup/restore, crash and cross-project constraint tests.
2. Implement immutable evidence/releases and fenced adoption repository operations. Real SQLite concurrency/process-exit tests must prove atomicity and exact replay.
3. Build pinned serving and isolated verifier execution. Test head changes between HTML/assets, foreign revisions, stale contracts, forged results, expired authority and hostile navigation.
4. Wire API/UI with exact identity and provenance. Run real browser checks against pinned artifacts; protocol fixtures are insufficient.
5. Exercise publish/unpublish/retry/rollback and failures between artifact verification and pointer commit; verify target retention and recovery scope.
6. Complete production image, origin/proxy, model, backup/restore and deployed smoke gates before rollout.

All implementation and acceptance gates remain open.

## Sources and product direction

Lovable documents explicit snapshot publishing, unpublished edits, audience and configurable security gates: https://docs.lovable.dev/features/publish (retrieved 2026-10-01). Replit's historical rollback article, updated 2024-08-30, describes new rollback deployments, configuration differences and retained-build availability: https://replit.com/blog/introducing-deployment-rollbacks (retrieved 2026-10-01). These are official design evidence, not paid-account testing or current Replit retention guarantees.

Atom's proposed delivery record connects requirements, exact artifacts, independent verification, release and explicit recovery scope, with explainable stale/blocked states. This is a design direction, not an exclusivity or implementation claim.

Migration prerequisite progress (2026-10-01): supported-version backup/verification now handles v1 under writer exclusion, with real WAL/restore and Linux evidence. v1 schema remains locked. Journal version CHECK and producing-attempt-only revision constraints must be explicitly migrated before new release/adoption behavior; no new schema is enabled.

Offline schema progress: v2 provides structural request/result/release/publication identities, composite revision/contract/policy scope, immutable evidence and passing-result constraints. It does not supply verifier authentication, environment identity, head adoption or atomic repository APIs. Those requirements remain mandatory before release acceptance. Existing application rejects v2 until integration is complete.

Contract codec implemented: capture_contract validates key/title/detail/checks without coercion, emits versioned canonical UTF-8 and SHA-256; load_contract rejects duplicate JSON keys, invalid UTF-8/surrogates, unknown format/fields and size limits. List order and exact text are preserved; missing flow setup equals empty setup. capture_report re-derives check identities from stored canonical bytes, requires complete unique coverage and strict booleans, and emits a contract-bound report. These operations do not attest execution or verifier authority and are not yet connected to publication.

Intent reservation now resolves owner scope and reads actual stored requirements in one SQLite writer transaction. New requests require expected head/contract and no active run/attempt, with integer budget 1–900 seconds. Identical replay returns original immutable identity, even after expiry/contract changes; consumers must independently authorize dispatch and must not treat replay as a refreshed capability. Policy/runner inputs are trusted control-plane configuration, not public caller authority. Artifact-byte verification and verifier environment/authority remain separate unfinished prerequisites.

record_report is a trusted coordinator operation only, requiring separate future verifier authentication before exposure. It checks owner scope, uses the immutable captured contract, computes passed/failed from exact coverage, and rejects first submission before creation or after deadline. Exact report replay preserves the prior record; changed notes/results conflict. Contract changes during execution do not retarget historical evidence. Release policy must separately check freshness and authority; this ledger operation creates no release.

Termination ledger now supports owner-scoped cancelled/timed_out decisions with immutable exact replay. Timeout requires now>deadline; reports retain their inclusive deadline rule. The first committed report/interruption wins; later differing outcomes conflict. Interrupted JSON contains no fabricated per-check observations. Trusted recovery inventory returns at most a requested 1–1000 entries (default 100), rejects overflow and performs no writes. Coordinator must still stop/confirm browser processes and periodically reconcile; neither behavior is implemented by these methods.

Internal ReleaseRepository.publish now validates current owner, idle main workspace/head, expected pointer generation, current contract digest and passing report under configured policy/runner. It atomically writes immutable release metadata, advances the pointer and saves an exact request receipt. Changing replay input conflicts; replay after later releases returns history without pointer effects. This trusted internal operation is not publicly exposed: independent verifier authentication/provenance and physical artifact verification remain mandatory. Existing command receipt key prefix release: is reserved for this operation; event delivery, unpublish/rollback and isolated artifact serving remain open.

Internal unpublish now checks owner, current release, expected generation and live status under writer exclusion, increments generation, and stores a reserved unpublish: receipt atomically. Receipt failure rolls back visibility. An identical historical retry is observational even after republishing; a fresh stale command fails. Generated page/asset serving must still enforce live visibility when integrated.

resolve(slug, viewer, optional release_id) now requires live current publication, current audience access and selected release audience access within the same project. Anonymous reads require both audiences public; owner may access private history only while publication is live. Old public references cannot bypass current privacy/unpublish, and new public releases cannot expose private history. Each eventual asset request must call authorization again; resolution alone cannot invalidate already delivered/cached bytes.

materialized_release now verifies stored payload and manifest against captured artifact metadata, checks visibility again after IO, and yields a private temporary view removed on context exit. It cannot revoke bytes already returned or guarantee visibility throughout an eventual streamed response; serving must define its request boundary and cache policy. No legacy directory fallback exists.

materialized_release permits one concurrent view per process and rejects a waiter after three seconds with release_capacity. The slot is acquired before storage IO and released in finally. Current visibility is rechecked after extraction before yielding, so an intervening unpublish cleans temporary files and denies the view. Publication changes after the final check still require the eventual HTTP request/cache semantics to be defined.

Serving architecture is specified in content-origin.md: dedicated content site, durable per-version host mapping and separate private access. Existing path/query/iframe DOM flow must not be treated as isolation or independent verification. No HTTP cutover is enabled.

For a new publication on verified schema v3, fixed content binding is part of the release promotion transaction. Pointer readiness cannot commit before the binding. Allocation collision or receipt failure preserves the previous generation and mapping. Schema-v2 ledger behavior and historical receipt replay remain unchanged; migration does not retroactively claim content bindings or browser evidence.
