# Trusted delivery contract — design revision 1

Status: proposed, unimplemented. Covers FR-006/007/008/009/012 and SC-003/005. Current ready status, syntax validation and client-reported acceptance are insufficient to authorize enterprise publication.

## What is accepted

Freeze an input descriptor containing organization/project, source revision and content manifest, requirement-set digest, acceptance-contract digest, lockfile digest, runtime/Pi lock, build image digest and effective nonsecret environment/policy versions. Secrets are referenced by versioned opaque identity, never hashed plaintext exported in public evidence. A secret/config version affecting behavior invalidates the applicable environment checks.

Each contract check has a stable ID, requirement mapping, executable procedure, expected assertion, required environment and timeout. Agent-added checks are proposals; the agent cannot delete mandatory checks, rewrite their expected result or approve its own change to the contract. Reviewer authorization is checked when adopting contract changes. Skipped/unknown/infrastructure-failed checks are not passes. A successful build does not assert browser behavior, security, live model operation or recovery.

The generated workload runs without acceptance-signing or release credentials. A separately authenticated controller observes execution status, collects outputs, hashes artifacts and creates the evidence envelope. A file named test-results.json inside the workspace has no authority by itself. Workload stdout is untrusted; structured reports must match independently observed exit and process lifecycle. App-authored unit tests supplement, but do not replace, reviewer-controlled behavioral checks.

## Evidence and artifact integrity

Required envelope: unique runner invocation, exact input descriptor, builder/runner identity and version, start/end timestamps, termination cause, check IDs/results, artifact digest, sanitized log/screenshot references and their hashes. Use an allowlist of trusted signer/runner pairs; rotate/revoke identities through policy. A valid signature proves provenance under that trust policy, not correctness of the checks or security certification.

Build in a clean isolated environment from the frozen revision. Install locked dependencies through approved sources; record resolved material digests and network policy. Never mount the control-plane database, Docker socket, production SSH keys or other tenants' storage. Artifact manifest permits only supported regular files within its root, rejects path traversal, symlinks and device files, enforces limits and includes deterministic paths/sizes/hashes. Freeze after completion; no build-time writer may modify published bytes.

Acceptance is a server decision over an exact evidence set and policy revision. In one transaction check current authorization, matching project/input identities, all required pass results, evidence validity/age and trusted runner identity. Preserve rejected decisions and reason codes. Changed source, contract, dependency, runtime or relevant configuration requires new affected evidence. Historical evidence remains attached to its original subject; never relabel it as latest.

## Promotion and verification

1. A publish-capable actor submits accepted artifact ID, environment, expected current release version and idempotency key. Editing access alone is insufficient. Promotion requires current policy and acceptance, not a client-provided pass boolean.
2. Acquire environment deployment ownership, validate expected version, verify artifact bytes and compatible database migration plan. Record a prepared release with previous release identity. Build once; do not rebuild a different artifact during promotion.
3. Stage at a new immutable location and test readiness/behavior on that candidate. Existing traffic continues using the current release. No delete-then-copy of live directories.
4. Commit an atomic routing/pointer switch supported by the target platform; record actual switch receipt. Database and external routing are not assumed to share a transaction: recovery reconciles observed route identity against the durable deployment operation before retrying.
5. Verify deployed digest plus required live business checks, then mark active. If verification fails, restore the prior compatible pointer and test it; retain failed candidate and rollback receipts. A route-switch crash must recover to a known observed release or a visible reconciliation state.

Concurrent promotions use fencing/version checks; the stale deployment cannot overwrite a newer release. Unpublish revokes routing without erasing the artifact/audit record. Control-plane UI and untrusted preview/published content use separate origins with no shared authentication cookies.

## Recovery boundaries

| Resource | Evidence before deployment | Recovery meaning |
|---|---|---|
| Code/static artifact | Verified previous artifact, manifest and routing receipt | Switch to identical prior bytes; does not restore business data |
| Database | Consistent encrypted backup plus replay/log position, schema version and restore drill | Restore declared point under maintenance; reconcile writes beyond point |
| User uploads | Consistency-linked object versions/manifest | Restore matching object state, not just database rows |
| Provider/repository/email effects | Operation receipts and explicit reversibility classification | Reconcile/compensate where supported; cannot claim universal undo |
| Secrets/policies | Versioned references and recoverable key management | Authorized restore/rotation; do not resurrect revoked access blindly |

Use expand/contract schema changes where possible. A release whose migration makes the old binary incompatible cannot advertise automatic binary rollback. Restore into an isolated target and run business checks before using a backup for production recovery. Record actual RPO/RTO, excluded effects and any loss; SC-005's five-minute/30-minute targets remain unproven. A backup stored only on the failed host cannot cover host loss.

## Independent acceptance scenarios

DL-01: submit fabricated client report and forged runner identity; neither authorizes publication. DL-02: mutate source/contract/config/artifact after pass; promotion refuses mismatched/stale subject. DL-03: generated code attempts signer access or cross-project report reuse; deny and audit. DL-04: stop deployment before staging, during switch and after switch before receipt; old/new observed digest stays explainable and no partial directory is served. DL-05: two promotions race; stale expected version cannot win. DL-06: live check fails after switch; prior compatible release is verified. DL-07: restore database and uploads to a declared point on another isolated host and exercise actual business behavior. DL-08: clean-room export rebuild uses documented configuration and locked inputs, with differences investigated rather than ignored. These scenarios are definitions, not passed tests.

## Source-backed reasoning

Current `backend/app/routers/publish.py` checks ready/index.html and calls copy_tree; `projects.py` accepts client reports; `services/artifacts.py` explicitly performs a deterministic generation gate, not browser acceptance. These are separate responsibilities to replace through tested boundaries.

[SLSA provenance v1.1](https://slsa.dev/spec/v1.1/provenance) distinguishes builder identity, invocation metadata and resolved inputs; consumers must trust specific signer/builder pairs. Atom's envelope design borrows that provenance separation without claiming a SLSA level. [GitHub secure use guidance](https://docs.github.com/en/actions/reference/security/secure-use) warns that self-hosted runners may be compromised by untrusted workflows and that approval alone is not isolation. This supports ephemeral isolated workloads and keeping verification authority outside generated code. Both consulted 2026-09-30; the release state machine and business acceptance policy above are proposed Atom design.
