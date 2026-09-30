# Durable execution contract — design revision 1

Status: proposed, not implemented or accepted. Covers FR-004/005/012 and SC-002/004. The existing single-worker dispatcher remains the supported implementation until migration and two-worker fault tests pass. Lease durations below are design parameters to test, not achieved recovery guarantees.

## Command admission and identity

1. Authenticate the actor and resolve current organization/project capability before reading a replay receipt. A previously valid receipt cannot bypass revoked access.
2. Require an idempotency key for chargeable and mutating commands. Uniqueness is organization/project/key; digest includes action, canonical validated body, input revision and policy revision. Secrets are references, never part of persisted request bodies. Same key/different digest returns `409 command_conflict`; same digest returns the same execution identity.
3. In one short database transaction: lock project coordination and applicable budget accounts in stable ID order; validate input revision and active mutation constraints; reserve budget; insert execution, receipt and initial event/outbox. Return `202` only after commit. If the response is lost, replay returns the committed identity. A dispatcher crash between acceptance and pickup must leave durable queued work.
4. Only one active source-mutating execution per project. Parallel model-race candidates use separate attempt workspaces and reservations; adopting a candidate uses compare-and-swap against the original project revision. Read-only review jobs may overlap under configured capacity limits.
5. Rejected admission has no execution and no reservation. No model/network request occurs while holding admission locks. Finite lock/statement timeouts return retryable overload responses without ambiguous acceptance.

## Ownership and state transitions

Proposed claim mechanism: PostgreSQL transaction with ordered queue selection and `FOR UPDATE SKIP LOCKED`, followed by creation of a new attempt and increment of a monotonic fencing token. Queue polling is the durable baseline; notifications may reduce latency but cannot be the only wakeup mechanism. Exact database version and capacity remain infrastructure gates.

| From | Event and preconditions | Result |
|---|---|---|
| queued | Authorized claim, before deadline, capacity available | provisioning plus owned attempt |
| provisioning | Isolated workspace ready, owner still valid | running |
| provisioning/running | Current owner reports valid output before deadline and no winning cancellation | succeeded; immutable candidate revision, not product acceptance |
| any nonterminal | Deadline reached | timed_out intent; revoke new operation authorization and confirm isolation termination |
| queued | Cancellation transaction wins before claim | cancelled; release unconsumed reservation |
| provisioning/running | Cancellation requested | persist intent; prohibit new paid/side-effecting operation; worker termination handshake |
| provisioning/running | Lease expires | attempt lost; reconcile effects and isolate old worker before retry decision |
| nonterminal | Nonretryable error or retry budget exhausted | failed with durable reason and cost reconciliation |

Use database time for lease comparison. Proposed initial lease 30 seconds, renewal at most every 10 seconds, recovery scan every 5 seconds; validate against SC-002's 120-second bound under real scheduler/database load. Every heartbeat, event, result and workspace promotion includes execution/attempt/fencing token. Updates require matching owner, unexpired lease and expected execution version. Zero affected rows means ownership lost and worker must stop. Never extend the original task deadline on retry.

Workspace writes happen in attempt-specific directories; a stale worker may damage only its abandoned attempt. Only a control-plane transaction with the current fencing token can register/promote its immutable snapshot. Database fencing alone does not prevent an already issued external request.

Cancellation and completion serialize on the execution row. If success commits first, cancel returns the existing terminal result. If cancel intent commits first, later success cannot become accepted output; preserve any produced artifact as cancelled-attempt evidence. A timeout/cancel terminal record includes `termination_status` (confirmed/pending/failed) and `effects_status` (resolved/unknown). Terminal task state must never imply that an external effect was undone. No replacement mutating attempt starts while an old sandbox can still access shared resources.

## External effects and retries

Before each externally visible operation, persist an operation identity, payload digest, destination capability and reservation. The broker rechecks current ownership and grant revocation, and supplies credentials only for the approved destination. Record provider receipt immediately when available.

| Observed result | Retry decision |
|---|---|
| Failure before any request could be sent | Retry within existing deadline/budget policy |
| Provider supports stable idempotency and receipt lookup | Retry the same operation identity after reconciliation |
| Timeout/disconnect after possible submission | `unknown`; query receipt/status, do not blindly resubmit |
| Irreversible operation with no safe receipt query | Stop dependent work and request explicit reconciliation; show known/unknown effects |
| Truncated model response | Preserve current narrow runtime recovery only if operation semantics, original deadline and budget permit; not a blanket tool replay |

Automatic retries use bounded backoff and jitter with finite attempt count. Model fallback is a new recorded attempt under an explicitly allowed provider/model policy, never silent substitution. Cancelled authorization revokes further broker calls; already transmitted requests remain subject to provider reconciliation.

## Budget and usage

Reserve atomically against every applicable account before paid dispatch. Estimates record currency/unit, price version, token cap and upper-bound assumptions. No integer overflow or floating-point balances. Provider event identity and operation identity enforce unique settlement. Failed and cancelled attempts retain actual usage; releasing a reservation does not erase consumed cost.

Unknown cost stays provisionally reserved until reconciliation or a recorded authorized accounting decision. A late bill above estimate is an appended variance, not hidden by clamping balances to zero. New spend is blocked while account debt or unresolved policy limits forbid it. Customer-facing credits and provider currency remain separate ledgers. Reservation reconciliation runs durably and survives worker/API restart.

## Events, observability and resync

State change, project sequence allocation and outbox insertion share one transaction. Delivery is at least once. Consumers deduplicate by project/sequence and never infer a missing terminal event means a task is still running. SSE endpoints replay from durable storage across API instances, with bounded buffers and periodic durable catch-up.

On expired/ahead/gapped cursor, return an explicit resync instruction with a snapshot version and cursor captured consistently. A client installs the snapshot then resumes strictly after that cursor. Authorization revocation closes subscriptions; replay checks scope again. Retention of token deltas must not delete audit, terminal outcome, receipt or cost records needed for reconciliation.

Telemetry correlates execution, attempt, operation, revision, provider connection ID and deployment SHA without prompts/secrets by default. Measure queue age, ownership loss, deadline latency, cancellation confirmation, unknown effects, reserved/actual variance and outbox lag. Readiness checks durable dependencies; liveness does not assert model availability.

## Evidence and test matrix

EX-01: 100 concurrent duplicate submissions across two API processes yield one identity/reservation; altered body conflicts; revoked actor cannot replay. EX-02: kill at admission commit/response gap and claim commit/dispatch gap; accepted work is recovered or explicitly terminated. EX-03: pause worker A through lease expiry, let B recover, then resume A; no stale event, result or promotion wins. EX-04: drop provider response after capture, prove no duplicate unsafe effect. EX-05: concurrent cancel/complete at controlled barriers, exactly one state outcome with accurate termination/effect status. EX-06: ten concurrent account reservations cannot overspend; duplicate/late bills settle once with visible variance. EX-07: API restart, duplicate event delivery and retention gap converge to authoritative snapshot. Execute 20 process-failure iterations, measure rather than assume the 120-second bound. All scenarios remain unexecuted.

## Basis and alternatives

Current evidence: `backend/app/services/commands.py` stores receipts after local registration; `orchestrator.py` owns in-process tasks; `events.py` uses process locks/fan-out; `credits.py` performs flat demo debits. Preserve existing semantics during an explicit migration, not by enabling extra workers on SQLite.

[PostgreSQL SELECT](https://www.postgresql.org/docs/current/sql-select.html), consulted 2026-09-30, documents SKIP LOCKED as useful for queue consumers but inconsistent for general reads. The lease, fencing, ledger and outbox rules above are Atom design decisions; the SQL feature alone supplies none of those guarantees. A dedicated workflow engine remains an alternative if operational evidence justifies it; introducing one is not a prerequisite for the initial bounded durable queue.
