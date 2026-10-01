# Partial checkpoint contract (T039 accepted)

## User-visible boundary

A successful sandbox `write` or `edit` is not a saved project revision. A partial
checkpoint becomes visible only after the trusted API has stored and verified an
immutable archive, registered an owner-scoped revision receipt, and confirmed
worker termination. The product calls this an **incomplete saved revision**;
it never calls the run successful, verified, publishable or accepted. If there
is no such receipt, the UI says the unfinished files were not saved. A base
revision ID by itself is not evidence of new generated files.

The user may preview an incomplete saved revision when it contains a safe entry
file, inspect its file list and explicitly start a new generation seeded from
that revision. The action says “从已保存版本继续生成”; it never promises to resume
the model's interrupted token stream or replay an uncertain tool operation.
If no new revision was registered, the action says “重新生成”. Existing accepted
publications keep pointing at their previous immutable release.

## Authority and state

- Only the existing scoped execution capability for the active owner, project,
  run, workspace, generation, base revision, broker attempt and deadline may
  request a partial checkpoint. A separate API endpoint accepts only
  `cancelled` or `timed_out`; malformed, expired, cross-workspace and replayed
  changed requests fail closed. The runtime never receives broker admin or
  artifact-store credentials.
- On model abort, the own runtime stops dispatching new tools and asks the API
  for a partial checkpoint using a bounded independent transport. Ordinary
  model/provider errors still use cancellation without a partial checkpoint.
  The API keeps a finite cleanup grace after the selected model budget; the
  grace is not additional model-generation time.
- The trusted coordinator serializes partial registration with admission and
  final completion. It reloads the exact active ledger attempt and broker
  identity, asks the broker to quiesce/export, verifies the bounded archive and
  semantic digest, stores it immutably, registers the revision receipt, checks
  the registration result, confirms the broker checkpoint, then revokes and
  observes termination with the original `cancelled` or `timed_out` outcome.
  The broker's workspace lock prevents a torn archive. A matching semantic
  digest to the base creates no new revision and returns a null receipt.
- A partial receipt is allowed alongside a non-success terminal outcome. The
  API's run/heat status remains `cancelled` or `timed_out`. The catalogue reads
  the committed revision and files; it must not derive partial bytes from tool
  events, the legacy heat file count, or an unconfirmed sandbox state. Publish
  and adoption still require their independent verification/release gates.
- The Node client accepts a partial receipt only if the API returns the exact
  closed/confirmed attempt, workspace, grant, broker identity, deadline,
  permitted outcome and registered receipt. The Python runtime stream boundary
  independently reloads that ledger receipt before surfacing it. No unknown
  network outcome is automatically replayed.

## Crash and race matrix

| Failure point | Durable fact | Required recovery/UI |
|---|---|---|
| Before broker quiesce | No new receipt | Revoke worker; report unfinished files unsaved. |
| Quiesced/exported, before artifact put | No new receipt | Revoke worker; do not advertise partial bytes. |
| Artifact put, before ledger registration | Unreferenced immutable bytes | Revoke worker; head unchanged; later GC may collect only after a separate proof. |
| Receipt registered, before broker confirmation | New head and exact receipt | Startup verifies stored bytes, fences the worker, retains the revision, records non-success outcome. |
| Broker confirmed, before termination observation | New head and exact receipt | Reconcile revocation/termination, retain revision; do not claim run success. |
| After closed/confirmed response, before browser receives it | Durable receipt and terminal outcome | Browser reload resolves catalogue and status; no duplicate revision on retry. |
| User Stop races a normal completion | At most one ledger decision and one revision | Serialize on the attempt; return the already committed result or an explicit conflict, never overwrite a successful decision with cancellation. |
| API or runtime process dies before receipt | No proven saved partial | Reconcile and revoke; never infer completion from worker files. |

The existing registration/receipt tables can represent a non-success outcome
with a receipt. Their behavior must be verified under each race before reuse;
no schema change is assumed. The 380edf5 baseline allowed cancellation to
override an unclosed success decision. A ledger correction now preserves
the first terminal decision across all supported schema versions. The existing
ledger/broker/coordinator paths passed 481 real Linux tests with locked
development dependencies and exit code 0. The scoped partial HTTP/coordinator
path passed changed/unchanged broker tests and four fault-injection tests on
Linux. Production serves `64ed268` on both API and broker. A live provider
`edit` followed by Stop registered a new cancelled revision; authenticated
file API, preview and Chromium showed the same verified bytes, explicit
continue action and disabled Publish. A subsequent API restart kept the receipt
and head without duplication, but revealed a sidecar namespace restart defect
that required broker recreation. The installed coordinated restart entry point
passes a systemd restart exercise. A separate live provider `edit` was followed
by SIGKILL of the API child before any partial receipt: startup reconciliation
closed the attempt with no receipt or new head, revoked the worker, and Chromium
showed only the prior files with retry wording. A fresh live
model-requested/Stop case had zero writes, a null incomplete receipt and the
correct browser retry wording. A later live 180-second deadline after six edits
registered a `timed_out` receipt and exposed the exact files in Chromium; both
the Publish button and API rejected publication. The unfinished generated
preview threw its own `mode is not defined` error, while the Atom workspace
had no page error. Generated-app correctness was not accepted by this gate.

## Acceptance gates

1. Real broker/Docker/storage tests checkpoint modified and unchanged
   workspaces under Stop and deadline, including concurrent file operations.
   Verify archive digest, receipt identity, exact head and file catalogue.
2. Fault injection at every matrix boundary proves no phantom saved files,
   no duplicate revision, no lost confirmed revision and no leaked worker.
   Restart the API after a registered partial receipt and verify recovery.
3. Own runtime protocol tests prove abort-only partial requests, bounded
   completion transport and independent Python ledger verification. Locked Pi
   source remains unchanged.
4. A live provider run is stopped after real writes. Persisted run/heat status,
   nonempty partial revision, browser file list and explicit continue action
   must agree. A second live run with no writes must show “重新生成”. Browser
   preview and publication must not claim acceptance of an incomplete output.

T039.2 and T039.3 passed their scoped acceptance. The full 27-case real Linux
broker/Docker/store/HTTP/Node integration file passed on 2026-10-02, including
a real concurrent write/export lock race and injected failures during broker
export, artifact put, ledger registration, broker confirmation and revocation.
Production live-provider Stop/deadline, process-death recovery and authenticated
browser evidence established the user-visible boundary. These gates accept only
verified incomplete-revision behavior; verified publication and enterprise
release acceptance remain separate and open.
