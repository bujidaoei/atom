# Plan: Runtime sandbox ownership
Branch codex/007-sandbox-lifecycle; spec [spec.md](spec.md).

## Technical Context
Existing TypeScript/Node 24 runtime and SandboxClient port. No dependencies, database changes or Pi source edits. Actual ProductAgentRuntime currently creates sandbox before ModelRuntime.create/provider/tool initialization, and uses three later cleanup sites. Session disposal can also throw before destroy.

## Constitution Check
PASS before/after design: unify ownership in own runtime, no secrets or fallback, scoped real tests, keep broader release gates open. No unbounded retry added; adapter timing/reconciliation remains explicit responsibility.

## Design and Structure
Add `runtime/packages/agent-runtime/src/sandbox-lifecycle.ts` with `withSandbox(client, runId, enabled, operation)`: acquire when enabled, run callback, await destroy in finally; aggregate original operation and release errors on dual failure with fixed outer message. Preserve exact thrown values, including undefined. Failed acquisition never enters ownership scope. Disabled path calls operation with undefined and no sandbox calls.

Wrap all post-acquisition work in ProductAgentRuntime.run with this helper; remove scattered destroy catches and final destroy. Keep session disposal in its existing inner finally so outer sandbox release still executes if disposal throws. No checkpoint API change. Reindent callback body consistently.

Tests in `runtime/src/sandbox-lifecycle.test.ts`: counting/fault-injecting adapter only for lifecycle contract; actual ProductAgentRuntime plus LocalSandboxClient for early gateway model getter failure, before any network call. Existing recovery-integration/workspace tests exercise real Pi/tool behavior. No fake backend accepted as broker evidence.

## Delivery
Exit-path tests → ownership helper/runtime integration → runtime regressions/Pi integrity → Spec Kit evidence and commit. No production enablement or deployment implied.
