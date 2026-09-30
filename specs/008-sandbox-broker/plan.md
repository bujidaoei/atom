# Plan: Isolated sandbox broker
Branch codex/008-sandbox-broker; input spec.md. Feature remains open until all integration gates pass.

## Technical Context and Structure
Python 3.12, existing PyJWT/FastAPI, standalone broker package `backend/app/sandbox/` independent of API database/settings. Linux Docker host. TypeScript HTTP adapter in `runtime/src/`; preserve locked Pi. Use actual snapshot component 006 and ownership scope 007.

## Constitution Check
PASS for incremental implementation: specifications/tasks/evidence precede code; finite ownership, real denial/fault tests, no production enablement before gates. Parent scope and unanswered deployment capacity questions remain open. No secrets in repository.

## Design
1. Grant codec: fixed HS256, explicit type/issuer/audience, strict bounded JSON schema, integer times/fence, logical IDs only, SHA-256 input revision and files-v1 capability. Dedicated random 32+ byte signing key held by trusted control plane and broker, never runtime/workload. Broker is trusted to mint with this shared key; stronger signing separation/key rotation is future hardening. Token verification alone does not implement revocation or authorization admission.
2. Host-local SQLite registry with explicit versioned schema/bootstrap, transactional create intent, unique grant ID/attempt, canonical claim digest, state/fence/deadline and owned container name. Persist revocation, operation intent and termination status. Single broker process owns dispatch; restart reconciles before readiness. This is not the distributed queue or HA database.
3. Docker driver uses fixed approved image digest/profile; no caller-selected mounts/flags/env. Bounded subprocess IO/timeouts, labelled ownership, independent lifetime, nonroot/read-only/drop-cap/no-network/tmpfs limits. Registry controls all operations. Uncertain creation/termination goes through reconciliation, no blind retry or local fallback.
4. Typed file-helper operations: current shell-shaped SandboxClient cannot safely be treated as arbitrary shell authorization. Add structured workspace-operation port and update own wrappers/adapter together; broker maps operations to fixed helper programs. Retain exact pagination/write/edit behavior and tool names. No command string allowlist guessing.
5. Explicit checkpoint path freezes broker operation admission, waits for active helper termination, exports while container alive, verifies snapshot and conditionally registers current fence. Destroy only cleans. Recovery seeds new attempts from last registered snapshot; preview reads committed revision.
6. HTTP boundary: separate administrative service credential for control-plane admission/revocation; runtime presents bearer grant for scoped operations only. Bounded request/stream deadlines. Production readiness requires broker and reconciliation; migration keeps old data until verified import and pointer switch.

## Phases
Grant validation → registry/reconciliation → Docker/file helpers → HTTP and structured runtime adapter → snapshot registration/migration → real fault/acceptance. Do not expose incomplete endpoints. Grant library can be tested independently while remaining tasks stay open.

## Validation
Unit negative JWTs with actual cryptographic verification; real SQLite concurrency/restart tests; actual Docker limits/cancel/restart; actual Pi and file tools through service; stale fence and failed registration tests; lock verification and product suites. Tests use synthetic data, isolated roots and no paid operations unless authorized.
