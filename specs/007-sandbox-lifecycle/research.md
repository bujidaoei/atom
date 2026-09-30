# Source-based decision
Inspection at 42419d9: sandbox allocated near product-agent-runtime.ts:234, ModelRuntime/provider/tool initialization follows before catches around plugin/session creation. Final destroy follows runtime.dispose and can be skipped if disposal fails. Use one outer ownership scope instead of adding another narrow catch. Existing own-runtime sources are authoritative for this defect; no external product claim required.

Alternatives rejected: catch every individual initialization step (fragile), auto-publish in destroy (wrong success semantics), swallow cleanup failure (false success), retry destroy here (could duplicate external effects without broker idempotency). AggregateError retains both causes without exposing their messages in the outer message.
