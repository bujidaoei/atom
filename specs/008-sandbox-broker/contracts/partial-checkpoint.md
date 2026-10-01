# Partial checkpoint contract (design; not implemented)

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
development dependencies and exit code 0; the corrected ledger is deployed in
the healthy 6386e47 API/broker pair. The new partial-checkpoint paths remain
open. Current API timeout still
eagerly revokes the worker and must be corrected before partial checkpoints
can work. The broker's grant window and cleanup grace must be long enough to
permit the bounded checkpoint while still finite.

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

This contract is a design artifact. T039.2/3 remain open until implementation,
fault injection and live browser acceptance satisfy these gates.
