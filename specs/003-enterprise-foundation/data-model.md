# Enterprise data model — proposed invariants

Status: design revision 1; no migration or schema implemented. IDs are opaque; all times UTC; monetary amounts integer minor units with explicit currency/unit and price version. Never mix USD cost, tokens and product credits in one balance.

## Identity, policy and provider

| Entity | Essential fields | Integrity rules |
|---|---|---|
| Organization | id, name, status, policy_version | Deactivation blocks new execution, retains evidence |
| Membership | organization_id, user_id, status, capability_set, revoked_at | Unique organization/user; final owner protected |
| ProjectGrant | organization_id, project_id, principal_id, capabilities | Project and principal belong to scope; no unscoped lookup |
| Project | id, organization_id, creator_id, title, current_revision_id | Current revision belongs to same project |
| PolicyRevision | id, organization_id, content_digest, effective_at | Immutable revision; lower-level policy only tightens |
| ProviderConnection | id, organization_id, owner_id, endpoint, credential_ref, revision, network_policy_id, status | Endpoint/credential/policy resolved atomically; no independent fallback |
| SecretEnvelope | ref, organization_id, ciphertext, nonce, key_version, status | Authenticated encryption with scope-bound associated data; no API plaintext reads |
| Session | id, user_id, expires_at, revoked_at | Revocation and membership checked on privileged requests |

## Intent, execution and concurrency

| Entity | Essential fields | Integrity rules |
|---|---|---|
| RequirementRevision | id, project_id, requirement_key, content_digest, acceptance_contract_digest | Immutable; change creates revision |
| CommandReceipt | organization_id, project_id, key, action, canonical_digest, execution_id, response | Unique scope/key; replay only after current authorization; different digest conflicts |
| Execution | id, organization_id, project_id, actor_id, state, deadline, cancel_requested_at, policy_revision, input_revision, version | Durable accepted intention; terminal result immutable; retry creates new attempt/history |
| Attempt | id, execution_id, ordinal, worker_id, fencing_token, lease_until, state, result_revision, error_code | Unique execution/ordinal; active owner write requires current token and unexpired lease |
| RunEvent | organization_id, project_id, seq, execution_id, attempt_id, type, schema_version, payload | Unique project/seq; transactionally ordered; no secrets in payload |
| Outbox | id, event_id, delivered_at, retry_after | Written in same transaction as authoritative change; duplicate delivery allowed |
| ExternalOperation | id, attempt_id, operation_key, payload_digest, provider_request_id, state, result_ref | Unique scoped key; uncertain outcome reconciles before retry |

Execution states: queued → provisioning → running → succeeded/failed/cancelled/timed_out. Retryable worker loss records attempt failure before a replacement attempt; execution can return to queued only within original deadline/budget and retry policy. `cancel_requested_at` is an intent independent of state until worker termination/reconciliation confirms outcome. Unknown external effects are represented by ExternalOperation state `unknown`, never success or automatic safe retry. Task success does not imply acceptance.

Use database time for lease decisions. No network calls inside state mutation transactions. Lock project command registration and reserve budget atomically; database constraints enforce uniqueness under multiple API instances. A fencing number prevents stale writes but cannot undo an external call already made; external operation receipts handle that separately.

## Budgets

BudgetAccount: organization/project/principal scope, unit, limit, spent, reserved, period and version. Reservation: operation key, account IDs, reserved amount, price version, state. UsageEntry: immutable provider event identity, measured tokens/cost, price version, reservation ID, correction relation and reconciliation state.

Reserve from all applicable accounts in a stable lock order. Enforce spent + reserved <= limit for new authorization. Settle actual usage exactly once and release unused reservation. Unknown provider usage keeps a bounded conservative reservation pending reconciliation rather than being reported as free. Late actual cost exceeding estimate is recorded as a variance/debt and blocks new spend; do not falsify the ledger to preserve the limit invariant. Corrections append entries. Existing flat demo credits are imported as a distinct legacy unit, not fabricated provider cost.

## Delivery

Revision: project, parent revision, source digest, requirement-set digest, dependency-lock digest, environment-config digest, producing attempt. Artifact: immutable storage key, manifest digest, build image digest, source revision, created_at. Evidence: artifact/revision/contract/environment digests, runner identity and image, execution timestamps, exit result, log/screenshot refs, provenance. Acceptance: policy revision, evidence set, reviewer identity, decision and reasons. Release: artifact, environment, approval, state, prior release, deployment receipt and verification. Backup: environment, snapshot identity, consistency boundary, encryption key reference, restore-tested timestamp. RecoveryRecord: target release/data point, actual restored state, excluded external effects, evidence.

All cross-entity references enforce same organization/project via composite constraints or scoped parent validation inside the transaction; random IDs are not authorization. Objects referenced by accepted releases cannot be garbage-collected. Retention rules apply separately to transient token events, audit records, secrets and business artifacts; deletion policy and export must be specified before production.

## Migration and coexistence

Collaboration contract revision 1 adds RepositoryConnection (organization, provider host/repository immutable ID, installation/grant reference, selected base SHA), RepositoryChange (base/head/upstream SHAs, execution, pull-request receipt, conflict state), ConnectorGrant (principal/action/resource/environment/expiry) and WebhookReceipt (provider/delivery ID, payload digest, validation outcome, processing state). Enforce organization scope and delivery uniqueness; no raw credential or webhook authorization header in these records. Imported repository state does not itself grant project access. Environment-specific secret bindings must be explicit; build credit units and published-app operating cost remain separate.

1. Capture consistent SQLite backup and immutable workspace manifests; verify restoration before altering schema.
2. Deterministically map each existing owner to a personal organization and preserve project/run IDs. Keep a migration mapping and reconciliation counts; do not grant every member all imported projects.
3. Preserve legacy acceptance as client-reported evidence, never silently promote it to trusted acceptance. Preserve published bytes as legacy release snapshots requiring revalidation for new promotion.
4. Quiesce writes or implement a tested explicit change-capture window before final copy. Counts alone are insufficient: compare IDs, relationships, content hashes and ledger balances.
5. Cutover only after target validation; rollback requires source consistency. Once new writes occur, do not switch to a stale old database; replay verified changes or restore within a declared data-loss boundary.
6. Versioned migrations run once through a deployment job with lock ownership. Application startup checks schema compatibility and refuses incompatible versions rather than opportunistically creating tables.
