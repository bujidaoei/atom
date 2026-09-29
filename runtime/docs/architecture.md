# Architecture

WorkDude has one React product interface, two entry points, two execution locations, one product-owned
Agent Runtime, one pinned Pi source tree, and one Docker sandbox standard.

```text
Web ──HTTPS/WSS──> Platform API ──BullMQ──> Cloud Worker ──> ProductAgentRuntime ──> Pi source
 │                       │                       │                    │
 └─ shared React UI      ├─ PostgreSQL           ├─ COS artifacts     └─ Sandbox Broker ──> Docker
                         └─ Redis events

Electron Renderer ──frozen IPC──> Main ──utilityProcess──> Local Agent Host ──> same Runtime/Pi
                                      └─utilityProcess──> Local Broker Host ──> local Docker

Cloud Worker ──Bearer──> LiteLLM `/v1/chat/completions`
Desktop Local Pi ──platform token──> Platform API AI proxy ──Bearer──> same LiteLLM gateway
```

Web always uses Cloud. Desktop defaults to Local and can explicitly select Cloud after a platform
origin and access token are configured. No adapter silently falls back to another location.

## Pi boundary

`pi/` is the unchanged, pinned Pi fork and retains its own `pi/AGENTS.md`, history, packages, and
tooling. Product code imports built files produced from `pi/packages/*/src`; no external Pi SDK or
npm package is installed. `packages/agent-runtime` is the narrow anti-corruption layer that registers
the provider-neutral enterprise gateway, creates a Pi session, normalizes Pi events, and exposes only
approved workspace tools. The knowledge structured-completion path uses the same gateway boundary.

`packages/product-contracts/src/server-configuration.ts` is the single validated server configuration
boundary for LiteLLM, upload, object storage, and Feishu. Cloud Worker may use the protected gateway
credential directly. Distributable Desktop code never receives it: Local Pi uses an authenticated,
rate-limited, unbuffered Platform API proxy and keeps tools and workspaces on the local host.

## Product directories

- `apps/`: Web and Electron entry adapters.
- `packages/`: product contracts, Runtime, gateways, persistence, design system, and shared feature.
- `services/`: API, Worker, Broker, and migrations.
- `deploy/`: Compose stack, sandbox image, and server operations.
- `specs/`: SpecKit requirements, contracts, tasks, convergence, and evidence.
