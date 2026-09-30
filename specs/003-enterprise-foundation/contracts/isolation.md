# Workspace isolation contract — proposed revision 1

Status: design under validation; no broker implementation or enterprise isolation acceptance. FR-002/003/004/010 and SEC-05. Windows/Linux probes already showed LocalSandboxClient.exec is not an OS boundary. Retain own ProductAgentRuntime and locked Pi; replace the sandbox port implementation and lifecycle, not the agent loop.

## Boundary and data flow

Control plane authorizes one project/run and issues a short-lived signed grant for its logical workspace ID, base revision, permitted file/command capabilities, resource profile and deadline. Runtime receives this opaque grant and tool access, not broker administration authority. A separate trusted broker verifies grant signature/scope/expiry/revocation and maps logical IDs beneath its configured artifact root. Neither user nor runtime request may supply host mounts, Docker flags, image name, UID, network mode or arbitrary source directory.

The broker alone accesses the local Docker control interface. Runtime and API containers do not mount that socket. Broker configuration contains approved image digest, root directory, grant verification identity and finite resource profiles. No model/API/database/session-signing secret enters the workspace container. Broker authentication and run grants are distinct from runtime API authentication. Compromised untrusted workload cannot mint a grant or modify the broker registry.

Each attempt gets a new unprivileged container with read-only root, dropped capabilities, no-new-privileges, default restricted syscalls, PID/CPU/RAM limits, no published ports and network=none. The initial file-tool profile needs Python and POSIX sh only. Dependency installation or approved network access requires a separately designed egress profile; do not open default networking as a compatibility fix. Shared-kernel containers are a private trusted-team execution baseline; public hostile multi-tenant SaaS still requires stronger worker-VM/sandbox-kernel evaluation and host-level failure tests.

## Bounded workspace instead of an unrestricted host bind

Use a size-bounded writable workspace filesystem and bounded tmp. An ordinary writable host bind has no guaranteed project quota, even when container memory/rootfs are limited; it is therefore not the accepted initial implementation. Tmpfs is a candidate for initial bounded file-tool workspaces, charged against memory. Large builds need a separately verified quota-backed volume, not larger unchecked host access.

Import only regular files from a validated immutable source snapshot. Enforce path normalization, count/per-file/total limits, reject symlinks/hardlinks/device files and ambiguous paths before transfer. No .env, runtime session, agent configuration, platform DB or repository credential files are imported implicitly. Explicit application configuration must use a typed policy-approved reference; hidden filename filtering is defense in depth, not authority.

Existing runtime tool wrappers resolve user paths relative to their declared workspace and execute Python file helpers through SandboxClient.exec. Adapter maps that virtual root to /workspace without string-replacing arbitrary shell commands. Set ATOM_WORKSPACE_ROOT=/workspace inside the worker; file-tool command inputs are relative. WriteFile performs path confinement and atomic per-file replacement inside the worker, never host-side writes through worker-created symlinks. Broker returns bounded structured output and toolCallId; the runtime keeps current tool names and model session semantics.

On checkpoint or terminalization, stop accepting new writes and export a validated regular-file manifest with hashes and limits. Stage outputs under a new immutable revision and register using current attempt fencing. Preserve prior revision until promotion succeeds. A live preview reads a committed revision, not a partially copied host directory. Failed/cancelled attempts may retain a clearly labelled partial snapshot; they cannot become accepted automatically. If quota/OOM destroys uncheckpointed output, report that boundary instead of claiming all files survived.

The 2026-09-30 lifecycle experiment used the actual 006 exporter/receiver with a running nonroot container and no host mounts. Controlled writes completed before export; host verification succeeded. Stopping/restarting the same container removed its tmpfs contents. Importing the retained verified stream and re-exporting reproduced the exact bytes and revision. Therefore normal completion must quiesce authorized writers while PID 1 stays alive, export and verify, register the checkpoint, then destroy. Neither `docker stop` nor whole-container pause is an export barrier usable with `docker exec`. An abort that requires immediate destruction may lose uncheckpointed work; retain the last committed revision and explicitly report the loss. No promise of partial-snapshot retention after forced stop.

The first profile permits only the existing broker-authorized finite file-helper operations, with a per-attempt operation lock; it must reject arbitrary background shell operations. Quiescing acquires that lock after denying new operations and verifies the last operation has terminated. If termination is unknown or the worker can still mutate files, fail checkpoint rather than hash a racing source. Expanding to builds/arbitrary commands requires a separately tested descendant-process ownership mechanism. The experiment proves only controlled synchronous writes; it does not prove that barrier for arbitrary workloads.

## Lifecycle, cancellation and restart

Persist create intent and container ownership before exposing a sandbox ID. Idempotent create for the same grant returns the same owned attempt; changed parameters conflict. Attach broker identity, attempt, expiry and policy labels. The container has a finite independent lifetime so broker process loss cannot leave unbounded execution. A durable janitor reconciles broker registry and only its labelled containers, terminating expired/unknown ownership and retaining outcome evidence.

Exec requests have finite deadlines bounded by the attempt deadline, payload/output caps and concurrency quota. Cancellation/timeout terminates the container process tree, not merely the local docker CLI; verify termination and reject later exec/write calls. Do not release the workspace or launch a replacement mutation until termination is confirmed. On daemon unavailability, mark termination unknown and fail readiness/dispatch; never fall back to LocalSandboxClient. Broker restart reconciles and fences old grants before accepting work.

Docker stdout/status and workload output are distinct: user code cannot forge a successful control response. Validate control JSON schema and lengths. Do not log arbitrary command contents or environment by default; logs use operation ID, profile, duration, outcome and redacted error category.

Runtime lifecycle integration must also close initialization gaps: `ProductAgentRuntime.run` currently allocates its sandbox before model/tool initialization, while cleanup is distributed across later catch/finally blocks. A single ownership scope must cover every post-create operation, including initialization failure and session-disposal failure, with exactly one terminal broker operation. Existing `destroy()` is called for success and failure without an outcome; do not silently make it publish a snapshot. Introduce an explicit checkpoint/result path before accepted completion and retain destroy as cleanup. Recovery attempts must seed from the latest registered revision and cannot recreate a blank tmpfs under the same run ID after automatic destroy.

## Integration and migration gates

1. Prove candidate OS/resource profile with isolated synthetic probes; this is not product acceptance.
2. Implement broker registry, grant verification, bounded worker lifecycle and snapshot IO with negative tests.
3. Implement HTTP SandboxClient and run existing real write/read/edit/glob/grep and Pi recovery tests through actual broker/container; no mocks may close this gate.
4. Wire service readiness/configuration so production refuses a missing broker and runtime no longer has host execution authority. Development local adapter must be explicitly selected and visibly non-isolated, never a production fallback.
5. Migrate workspace references and preview to committed revisions with source ownership validation; failure before/after checkpoint, stale worker and cancellation tests must pass.

IS-01: synthetic platform env, host/other-project canaries and Docker socket inaccessible while approved file tools work. IS-02: traversal/symlink/archive attacks cannot affect host or other attempt. IS-03: actual memory, PID, workspace and timeout exhaustion stay inside one container with durable failure and peer survival. IS-04: external/private/metadata egress denied by network profile. IS-05: disconnect/cancel/broker restart/daemon failure cannot create unbounded orphan execution. IS-06: unchanged source seeds, edited export and failed promotion retain exact manifest identity. IS-07: expired/revoked/cross-project/forged grants cause no container creation or file mutation. All product scenarios remain unexecuted.

## Primary basis

[Docker security](https://docs.docker.com/engine/security/) identifies daemon control and arbitrary bind mounts as privileged attack surfaces. [Container run reference](https://docs.docker.com/engine/containers/run/) defines resource/mount/network options; configuration flags are not evidence of their enforcement. Consulted 2026-09-30. The grant, revision, checkpoint and lifecycle contract above is Atom's proposed design based on current code and reproduction evidence.

[Docker tmpfs](https://docs.docker.com/engine/storage/tmpfs/) documents data loss on container stop; [docker exec](https://docs.docker.com/reference/cli/docker/container/exec/) requires the primary process to remain running. Consulted and locally verified 2026-09-30 with synthetic data, not a production workspace.
