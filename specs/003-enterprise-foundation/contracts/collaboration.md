# Enterprise collaboration contract — design revision 1

Status: proposed, unimplemented. FR-001/003/007/009/012; US4. Existing owner-only projects are not silently treated as organization collaboration.

## Organizational authority

Identity, organization membership, project access and environment deployment authority are separate checks. Use security.md's capability matrix. A repository connection does not grant all members access to its imported projects; generated-app users are not console members. New projects are private and require explicit grants. Invitations are scoped, expiring and single-use; acceptance verifies intended identity and current issuer authority. No invitation or connector authorization is performed merely to research competitors.

Grant changes carry expected policy version, actor and reason; concurrent updates conflict instead of losing permissions silently. Revocation blocks future sensitive operations, closes streams and cancels queued authorizations while preserving audit evidence. Removing a developer does not erase their historical authorship. Final-owner transfer must be atomic. Privileged recovery uses a documented operator procedure and audit, not a hidden universal project role.

## Existing repository onboarding

Initial provider: GitHub through a narrowly scoped App installation; provider-neutral RepositoryConnection permits future adapters. Store immutable provider repository ID, installation ID, authorized organization, selected refs and effective permissions. Names/URLs are display metadata and may change. Enterprise host origins are administrator-configured and allowlisted; never accept arbitrary credential-bearing clone URLs.

Onboarding is read-only by default: verify the user may attach this repository, resolve an explicit base ref to a SHA, capture manifests and detect language/build/test configuration in isolation. Reading does not execute hooks, package scripts or repository-supplied agent instructions. Submodules and LFS require separately approved destinations and scoped credentials; unresolved dependencies block reproducibility instead of being silently omitted. Enforce file/size quotas and reject unsafe archive paths/symlinks according to artifact policy.

Present the proposed workspace, test commands, required network access and missing capabilities before enabling execution. Repository documents are task data, not authority to change organization policy or extract secrets. Persist onboarding commit and configuration revision so future runs do not unknowingly use a moved branch.

## Repository writes and conflicts

Agent work starts from a pinned base in an isolated attempt workspace. Preserve source commit, patch and resulting digest; create an Atom-owned feature branch only after write authorization. No direct protected-branch push, force push, branch-protection bypass or default auto-merge. A reviewable change contains requirement links, scope, actual test evidence and unresolved failures.

Before publication of a change, fetch the current target SHA. If it differs, perform a three-way comparison using the recorded common base. Conflict-free integration still produces a new revision and invalidates applicable acceptance. Conflicts return paths and base/ours/theirs identities for explicit resolution; never overwrite upstream under a generic sync action. Re-check the target head when creating/updating the pull request. Already pushed commits are reconciled by repository/branch/SHA receipt after transport failure, not pushed again under a new identity.

Pull-request checks and approvals are evaluated for their actual head SHA and trusted producer. Changed commits require current checks. GitHub permission does not override Atom release policy, and Atom acceptance does not override repository branch rules. On expired/revoked repository grants, stop new remote actions and preserve local work; do not fall back to another user's token.

Webhook processing verifies signature over raw payload before parsing/dispatch, bounds payload size, checks installation/repository scope and deduplicates provider delivery identity. Out-of-order events prompt authoritative ref/permission refresh, not blind state reversal. Store sanitized receipt metadata; never log headers/tokens or treat a webhook text body as agent instructions. Poll/reconcile after missed deliveries.

## Connector actions and environments

Every grant lists allowed action, resource, environment, principal, expiry and issuer. Read/search, create/update, destructive action and public sharing are distinct capabilities. Preview/test cannot obtain production grants automatically. Require an explicit production credential binding or an explicitly reviewed same-credential policy; absent production configuration blocks promotion. Library reuse creates project/environment grants rather than silently sharing an entire secret store.

Agent sees a typed secret reference and action result, not secret plaintext. Bind the action to current attempt ownership and external-operation receipt defined in execution.md. Disconnect revokes future use but cannot undo a message, payment, repository write or third-party credential; show residual effects and provider-side revocation requirements accurately.

## Export, retention and portability

Export an authorized immutable revision with source, lockfiles, artifact manifest, runtime lock, migration requirements, nonsecret configuration schema, license notices and redacted evidence. Do not include live tokens, cookies, platform session files, private provider logs or unrelated projects. Signed export manifests identify exact content; importing does not execute build scripts before policy review. No export assertion of reproducibility until a clean environment rebuild and behavior check pass.

Record retention categories for source/evidence/audit/cost versus transient output. Deleting a project first revokes execution, preview and connector access; asynchronous erasure tracks object/database/backup retention obligations and legal holds. Audit an erasure request and actual completion separately. Release-referenced artifacts are retained until policy permits removal. Do not promise immediate physical deletion from immutable backups.

## Independent scenarios

CO-01: two organizations, differing project grants, revoked member and final-owner transfer; unauthorized operations have no remote effects. CO-02: import an existing test repository including changed branch and an unapproved submodule; pin SHA and refuse unauthorized fetch. CO-03: concurrent upstream/local edits conflict without data loss, resolution creates a new subject and reruns gates. CO-04: revoke repository installation mid-run; no fallback token or new push. CO-05: invalid/duplicate/out-of-order webhook cannot authorize or repeat a write. CO-06: exported accepted revision rebuilds without original Atom DB or private environment, while secrets are supplied by the destination operator. CO-07: test credential cannot silently become production authorization. All scenarios remain unexecuted.

## Official basis and design choices

[GitHub App versus OAuth](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/differences-between-github-apps-and-oauth-apps) documents selected-repository permissions and short-lived installation tokens. [Webhook validation](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries) requires signature verification before processing. Atom's conflict, revision, export and permission contracts above are proposed design, not claims provided by those mechanisms.

[Atoms keys](https://help.atoms.dev/en/articles/12129564-keys-and-secrets) distinguishes Test/Production and project/library storage, including default Test-value reuse if no Production value exists. Atom deliberately proposes explicit environment binding. Sources consulted 2026-09-30; no live connector granted or external repository changed during research.
