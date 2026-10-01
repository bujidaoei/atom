# Enterprise research — evidence ledger

Date: 2026-09-30. Status: IN PROGRESS, not a completed Atoms full-flow test.

## Evidence rules
OBS = authenticated browser observation; DOC = official documentation, not independently exercised; CODE = source inspection, not security/load testing; DESIGN = proposed decision. A visible button does not prove a successful operation.

## Atoms observed journey
| ID | Step | Observation | Boundary |
|---|---|---|---|
| A01 | https://atoms.dev/zh/my-projects | OBS: logged-in workspace; empty project list; all/favorites and profile entries | No existing project to inspect |
| A02 | Dashboard | OBS: prompt, Build selector, agent roles, Discover, templates, connectors | No generation submitted |
| A03 | Build selector | OBS: general Build and Goal/planning options | Mode behavior not exercised |
| A04 | Workspace selector | OBS: workspace organization explanation, plan and credit balance | No purchase, invitation or setting change |
| A05 | Account menu | OBS: settings, plan, profile, help; settings navigation opens | Account identifiers excluded from artifacts |
| A06 | People | OBS: owner/active member row, invite field, role/status/usage/join-date columns | No invitation sent; editor restrictions not empirically tested |
| A07 | Connectors | OBS: GitHub, Supabase, Stripe, GA4, GSC, Ads, Asana, Box, Dropbox, Todoist, Linear | No connector authorized; listed services do not prove their actions work |
| A08 | Preferences | OBS: default model Auto; default project permission Public, described as link/Discover accessible; notification/sound/badge preferences | No settings changed; future test prompts must contain no private source or secrets |
| A09 | Dashboard → public Discover example | OBS: a public Hello World project detail has embedded app, separate browser-open link, save and clone controls | No save/clone executed; no owner chat, code or history access inferred |
| A10 | Public example → open in browser | OBS: published Hello World rendered successfully on a distinct `*.app.atoms.dev` origin | Public static page only; does not prove private preview, backend behavior, authentication isolation or publish/update workflow |

## Official source map
Accessed 2026-09-30; these are documented behavior and limitations, not observed incident rates.

| Source | Documentation finding | Atom design implication |
|---|---|---|
| [Quick start](https://help.atoms.dev/en/articles/12129545-quick-start) | Prompt, inspect, iterate, test, publish | Separate completion and acceptance |
| [Project chat](https://help.atoms.dev/en/articles/12129550-project-chat) | Queued requests, preserved partial work, activity/version cards, failure recovery; warns about repeated repair and apparent success without change | Durable commands and evidence-based completion |
| [History](https://help.atoms.dev/en/articles/12129557-project-history) | Restore/Remix differ; active work restricts restore; historical backend preview may be unavailable | Separate revision, execution and data snapshot |
| [Publish](https://help.atoms.dev/en/articles/12129577-publish-your-project) | Explicit live updates, security scan and live verification; restore need not reverse data/external actions | Immutable release and separate recovery contracts |
| [Share](https://help.atoms.dev/en/articles/12129574-share-a-project) | Project sharing differs from published app; visibility depends on owner/plan | Private by default, explicit audience |
| [Permissions](https://help.atoms.dev/en/articles/12129576-access-and-permissions) | Membership, project access and app-user identity differ | Separate control-plane and generated-app identities |
| [Connectors](https://help.atoms.dev/en/articles/12129568-integrations) | Scopes/actions vary; disconnect does not undo writes | Action-scoped grants and reconciliation |
| [GitHub](https://help.atoms.dev/en/articles/12129569-connect-github) | Guide supports new personal private repos, not existing/org repos; manual sync can overwrite conflicts; broad account OAuth scope | Existing enterprise repos, narrow grants and explicit conflict handling |
| [Workspace](https://help.atoms.dev/en/articles/12129584-workspace-settings) | Shared members, credits, connections and Cloud usage | Organization operational ownership |
| [Account](https://help.atoms.dev/en/articles/12129583-account-settings) | Role-sensitive defaults and preferences | Visible effective policy hierarchy |
| [Secrets](https://help.atoms.dev/en/articles/12129564-keys-and-secrets) | DOC: separate Test/Production and project/library scope; absent Production value reuses Test; deleting an entry does not revoke provider credential | Explicit environment grant; production binding cannot silently inherit; rotation tested in both environments |
| [Plans](https://help.atoms.dev/en/articles/12129587-plans-and-credits) | DOC: build credits and published-app Cloud/AI charges differ; grant/reset/rollover depend on account terms | Separate usage units and runtime budget; do not infer available funds or a spend cap from build credits |

## Broader research and code baseline
- [Seven-product official comparison](../../docs/research/2026-09-30-commercial-products.md): Cursor, Copilot, Devin, Replit, Lovable, Bolt, Claude Code. Documents limitations and remaining research, not subscription hands-on verification.
- [Current architecture audit](../../docs/research/2026-09-30-architecture-audit.md): 14 source-backed gaps, existing capabilities and verification directions. No production exploit or live secret inspection.
- Primary agent independently inspected provider settings/gateway, preview routing/iframe, SQLite engine, event bus and local sandbox. Findings support prioritizing trust boundaries.

## Decisions, rationale, alternatives
1. DESIGN: establish provider credential binding, untrusted preview origin and worker isolation before multi-user expansion. Concrete source findings motivate this; adding team screens alone cannot establish enterprise safety.
2. DESIGN: retain modular application and own runtime, introduce adapters at demonstrated trust boundaries. Immediate microservice rewrite rejected: no operational or migration evidence supports its cost.
3. DESIGN: evidence tied to exact revision and environment, independently executed. Client-reported checks and agent prose remain feedback, not certification.
4. DESIGN: distinct recovery scopes for session, workspace, application and data/external effects. A single rollback button cannot promise all effects are reversible.
5. DESIGN: no HA claim from single-host deployment. Redundant fault domains and real failure drills remain acceptance requirements.

## Differentiators to validate, not claims of market exclusivity
- Evidence-backed delivery: requirement → scoped change → revision → independent test → acceptance → release; modified revisions invalidate old approval.
- Explainable recovery: each operation states covered resources and irreversible effects; unknown external outcomes reconcile before retry.
- Quality per cost: extend existing model races with identical acceptance contracts and real cost; rank correctness before speed, no invented scores.
- Portable enterprise control: keep runtime and deliver reproducible artifacts, policy and deployment ownership to the customer.

## Open gates
- Atoms generation → tool/file inspection → queued change → stop/resume → history → restore/remix → export → publish/update/live verification. Credit allowance question remains pending; no paid generation authorized by silence.
- Read connector catalog/policy panels without connecting customer repositories or services for research.
- Official incident/release-note review; dated primary evidence needed before generalizing failures.
- Determine customer priority, actual server resources, domains/certificates and available redundant infrastructure.
- Reproduce source risks locally with synthetic secrets and isolated targets before implementation/production changes.

## Official incident sample — 2026-09-30 retrieval

| Incident source | Dated fact | Design inference, not a proven Atom capability |
|---|---|---|
| [Cursor Dockerfile builds](https://status.cursor.com/incidents/lh1fpdkb4kcp) | 2026-09-23 17:14 UTC investigation; resolved 18:43. New Dockerfile builds affected while existing agents kept their current image | Separate environment provisioning from active execution; preserve known-good images |
| [Cursor authentication](https://status.cursor.com/incidents/r44l5qk34kj1) | 2026-09-18 23:02 UTC investigation; resolved 23:13. Provider-related sign-in/dashboard failures; existing sessions expected to continue | Model authentication dependency health separately from active task ownership |
| [GitHub history](https://www.githubstatus.com/history) | 2026-07-29 Fable 5 failures had model-specific concentration; official history discusses endpoint redundancy | Per-model telemetry and controlled failover; do not hide a degraded model in aggregate availability |

Incident update timestamps are not guaranteed outage-start/end times. This is a small diagnostic sample, not a vendor reliability ranking. Atoms-specific incident history has not yet been established; absence of search results does not prove absence of incidents.

## Continuation: security design and controlled reproduction

- Added proposed security contract, data invariants and independent verification protocol. These are unimplemented designs. Drafting a source-backed security boundary can proceed independently of paid competitor generation; final infrastructure/API decisions remain gated.
- `scripts/research/probe_provider_binding.py` executed actual `_payload` → `list_models` → HTTP request with temporary SQLite and a loopback receiver. Synthetic managed credential reached the custom user endpoint: VULNERABLE, exit 1. This proves model-discovery fallback exposure in the tested source; generation uses similar source logic but has not yet received its own network reproduction.
- [OWASP SSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html) informed redirect/DNS/address defenses; [OWASP CSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html) informed origin/token/cookie requirements. Consulted 2026-09-30.
- [PostgreSQL current SELECT documentation](https://www.postgresql.org/docs/current/sql-select.html) permits SKIP LOCKED for queue-like consumers while warning it gives an inconsistent view. It is a candidate for task claiming, not proof of exactly-once external effects. Queue technology/version remains undecided pending operational validation.
- [Docker security](https://docs.docker.com/engine/security/) and [rootless guidance](https://docs.docker.com/engine/security/rootless/) support reducing privileges; neither establishes sufficient hostile multi-tenant isolation on its own.

## Durable execution and trustworthy delivery — 2026-09-30

Added proposed contracts/execution.md and contracts/delivery.md. [PostgreSQL 17 SELECT](https://www.postgresql.org/docs/17/sql-select.html) was checked for the locally available experiment version; separate real sessions verified nonblocking queue claim and guarded stale writes. This is a database mechanism experiment, not an application reliability result.

[SLSA provenance v1.1](https://slsa.dev/spec/v1.1/provenance) separates builder identity and invocation/input records. [GitHub secure use](https://docs.github.com/en/actions/reference/security/secure-use) explains the risks of untrusted code on self-hosted runners. Design inference: independently controlled evidence identity and isolated verification workloads are necessary; an approval screen or signed agent-authored report alone cannot establish trustworthy acceptance. No SLSA level or certification claimed.

## Collaboration and execution boundary — 2026-09-30

Official Atoms secret and credit references above reviewed in detail without editing the account or spending credits. New proposed collaboration.md covers existing repositories, scoped grants, pinned revisions, conflict handling, webhook verification and portable export. GitHub's [App permission model](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/differences-between-github-apps-and-oauth-apps) and [webhook signature validation](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries) provide primary integration guidance. A direct Devin integration page lookup failed; no additional Devin behavior inferred from that failure.

LocalSandboxClient.exec reproduced environment inheritance and access to a synthetic file outside its workspace on Windows and Linux. This confirms absence of an OS boundary in that class, not agent exploitability. Runtime server currently filters tools to glob/grep/read_file/write/edit. Do not enable arbitrary command/build tools before isolated execution passes SEC-05. See evidence.md for exact scope and results.

## Isolation profile validation — 2026-09-30

Revisited [Docker security](https://docs.docker.com/engine/security/) and [container execution options](https://docs.docker.com/engine/containers/run/). Proposed separate broker rather than giving runtime Docker administration. A disposable Python container demonstrated readonly root, absent inherited canary/socket, denied network and actual disk/PID/memory exhaustion under configured limits. Exact image and limitations are in evidence.md; this is not integration acceptance. Quota-bounded workspace requires explicit snapshot import/checkpoint/export and current-attempt ownership; plain directory bind and env filtering alone do not implement the requirement.


### Governance/retention research refresh — 2026-10-01
Official Atoms [history](https://help.atoms.dev/zh/articles/12129557-project-history) and [publishing](https://help.atoms.dev/en/articles/12129577-publish-your-project) reinforce separate source/target selection and code/data/external-action recovery verification. [GitHub streaming](https://docs.github.com/en/enterprise-cloud@latest/admin/monitoring-activity-in-your-enterprise/reviewing-audit-logs-for-your-enterprise/streaming-the-audit-log-for-your-enterprise) distinguishes finite continuity buffers and receiver acceptance limits from retained copies; [GitHub API](https://docs.github.com/en/enterprise-cloud@latest/admin/monitoring-activity-in-your-enterprise/reviewing-audit-logs-for-your-enterprise/using-the-audit-log-api-for-your-enterprise) uses different windows for ordinary audit versus Git events. [GitLab audit](https://docs.gitlab.com/user/compliance/audit_events/) documents indefinite retention, while [streaming](https://docs.gitlab.com/user/compliance/audit_event_streaming/) separates owner deactivate/delete and receiver dedup. These different policies justify explicit Atom policy/obligation modeling, not borrowing one vendor TTL.
Current code plus real SQLite tests prove configured-only status can omit retained old-destination backlog. New receiver acknowledgements cannot settle old receiver obligations. Decision: persistent destination registry and generation-fenced administrative transitions precede any retention/pruning implementation; preserve existing v1-v5 definitions. Detailed proposed contract: specs/008-sandbox-broker/contracts/audit-governance.md. Recovery-manifest product design extends existing evidence chain without implying a delivered UI. Direct atoms.dev/zh/my-projects web fetch returned Internal Error; this does not prove product downtime and provides no new authenticated/paid-flow evidence. No vendor audit-stream retry/retention behavior beyond documented sources is assumed.

## Product workflow refresh — 2026-10-01, incident-led

The user's real production screenshots exposed two separate race failures: one heat rejected after three seconds of API coordination (`execution_busy`), and one model reached its explicitly selected 180-second limit. A different fresh project failed during Mike's sandbox setup with generic `broker_http_error`. These are stronger local evidence for prioritizing bounded admission, precise failure provenance and resumable work than any competitor marketing claim. They also show that a four-model option must be backed by actual four-way operational capacity; presenting the option alone is not a commercial-grade guarantee.

Atoms authenticated-flow boundary, 2026-10-02: a fresh real Chromium session navigated to https://atoms.dev/zh/my-projects and reached https://atoms.dev/zh/login (HTTP 200). The public login view offered Google continuation or email and displayed marketing claims about real applications, operations and ownership. This is direct browser evidence of the unauthenticated redirect and visible entry choices only. It does not establish the signed-in project dashboard, project creation, pricing, agent workflow, code export, publication or recovery behavior. The screenshot is a local ignored research artifact at `.logs/atoms-my-projects-guest-20261002.png`; do not infer product implementation from its promotional copy. Authenticated hands-on comparison remains open.

Official [Atoms Working with Agents](https://help.atoms.dev/en/articles/12129548-working-with-agents) describes a visible Working Process, explicit plan approval, version-card preview and recovery paths; [Atoms Dashboard Overview](https://help.atoms.dev/en/articles/12129546-dashboard-overview) describes workspace-scoped project discovery and project reopening. Official [Replit Agent](https://docs.replit.com/features/agent/overview) documents plan review, regular testing/checkpoints and subsequent publishing. Official [Cursor Checkpoints](https://docs.cursor.com/en/agent/chat/checkpoints) describes local agent-change snapshots distinct from Git history. [GitHub Copilot enterprise audit](https://docs.github.com/en/enterprise-cloud@latest/copilot/how-tos/administer-copilot/manage-for-enterprise/review-audit-logs) documents agent activity search and a finite audit retention window; it explicitly excludes local prompt/session content from that log. [Vercel Git deployments](https://vercel.com/docs/git) documents per-branch previews and production deployments from a designated branch. These sources support a differentiated Atom direction: a truthful per-run evidence trail linking user-approved contract, bounded execution admission, immutable artifact revision, actual checks and publish decision, with explicit unknown/timeout state rather than cosmetic progress percentages. This is a design inference, not an implemented or vendor-equivalent capability.

The public `https://atoms.dev/zh/my-projects` page could not be opened by the available web reader in this refresh. Replit, Cursor, GitHub and Vercel facts above come from official documentation, **not** hands-on authenticated operation of their products. Such product-operation evidence remains open; no account creation, paid run or third-party workspace mutation was performed. Do not claim the user's requested cross-platform practical evaluation complete on this basis.
