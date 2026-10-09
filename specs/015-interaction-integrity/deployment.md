# Deployment runbook and identity

Source implementation: `9e36c86e2aa77af2336e307e9221b65f5cda6dc1`, feature/main synchronized. Clean root-owned checkout `/home/ubuntu/atom-releases/9e36c86`.
Application image: `sha256:2f55183c224f2513d6b434cfc26af82c059b132de982995c7ca289b156eb12e4`, required atom.revision and OCI source labels; frontend base `/atom/`.
Verifier worker: `sha256:cc2185c38baf4956d3ab12c7b9ad7ab3550f36c817776159f733091b0bb30c1b`, OCI source identity,4real COS artifact checks passed with production sandbox/seccomp/no-network profile.

## Required operation
Final exact-labeled image tests and current/successor preflight precede cutover. Under the existing protected host lock, preserve root-private publication config, replace only its worker-image setting with the tested exact image, and invoke ip_forward_transaction.run_locked for schema19. This uses the existing storage PUT/readback/inventory gate, writer quiescence, verified paired backup, identity/journal, candidate preparation and strict-TLS exposure. Do not bypass a failed gate.

## Recovery boundary
Before successor durable writes, existing guarded journal recovery may restore the sealed source generation. After successor writes, retain successor data and use forward correction; never overwrite with an old backup. Retain the paired backup and previous source containers through acceptance. Active forward-candidate data is live data, never cleanup material.

## Acceptance
Require exact serving revision/image; six healthy service containers; matching new worker image/runner policy; normal trusted HTTPS health with storage=true; unchanged logical receipts for original4projects and their conversations/requirements/runs/revisions; unchanged artifact digests;24real TLS production preview browser scenarios. Separately exercise a real provider-generated form app through the logged-in owner workspace and revision-bound server verifier before accepting the journal. Record results, identity and limits in evidence.md, then synchronize documentation to main.

Status: accepted on 2026-10-09. Final exact application image passed137 tests plus10 subtests; exact worker passed all4 genuine artifact flows. Protected cutover unit exited0; journal9e36c86e2aa77af2336e307e9221b65f5cda6dc1 is accepted after24 trusted-TLS original-artifact browser scenarios, the real provider application12/12 verifier result and owner-workspace mouse/keyboard/reload checks. Six services healthy,116 live origins, original4 projects' logical data unchanged, foreign-key errors0.

Verified paired backup: `/var/backups/atom-cutovers/forward-pre-9e36c86e2aa7`, manifest SHA256 `bb1fcb9046b8ea2a92c54c976d1dcb779349c8451ec0510b0ef16eb393a4c54a`. Active live data: `/var/backups/atom-cutovers/forward-candidate-9e36c86e2aa7`. Storage inventory capture SHA256 `901e9f46e597418492e2f5c18bd123fc0691c33522f0ef8e19faeffbe6469bc9`.

Successor durable writes occurred during genuine provider acceptance. Retain successor data for forward correction; restoring the old database would discard those writes. No backup/live-data cleanup was performed. Final documentation synchronization does not change the tested/deployed implementation image. Users with an already-open workspace should reload it to receive the updated compiled iframe policy.
