# Deployment — workspace performance
## Prepared 2026-10-04
Executable source: fbfbb89aa7e13e98b0d015889c34bc46d5753f5a, clean root-owned /home/ubuntu/atom-workspace-release.
Image: sha256:f7af12541d584742949745fe2369b48c2dce609e3d32013ba8d1d75e737ebe4f, exact atom.revision label and /atom/ frontend base. Build unit atom-build-workspace-v2 exited0. Initial build command failed before build because the target fetch used FETCH_HEAD rather than a remote-tracking ref; corrected by checking out the full fetched commit. No production change occurred on that failed attempt.
Exact image: Pi1905 checksum boundary, compileall and nginx -t pass. Actual Linux revision route integration passed1/1, including owner isolation, corruption and legacy preview protection. Linux artifact/COS suites passed28/28. A newly added test initially attempted to mutate immutable ledger records and was correctly rejected by the existing DB trigger before reaching its intended assertion; corrected test validates full-identity cache misses without modifying the immutable ledger, then passes. Production code unchanged by that test correction.
Protected current/successor preflight returned ready_for_forward_transaction: original fd191e5 image143491f..., six exact service IDs,80 project origins, Caddy SHA256 b4347fd658c690a533fb42c4bea634608f7bc8bb7fd74d25b811aa8219320011.
Before deployment, existing public port20073 returns certificate-verified HTTP200 with HTML SHA256 4a3b8558d8863990a5fc323f1bbf30895d9f36430c49a738451a9afca582a980.

## Cutover gate
Pending full regression review. Run existing deploy/ip_forward_transaction.py under a bounded target-local systemd service with protected configuration, source fd191e5, exact successor and image. It performs host locking, writer fencing, paired verified backup, separate candidate data and retains previous service containers. Do not manually replace live DBs.

## Recovery
Before exposure, the transaction uses existing phase-based source restoration. After exposure, invoke deploy/ip_forward_recovery.py with protected config/publication file and exact successor revision; it evaluates durable writes and refuses unsafe rollback. Preserve candidate data when writes have occurred; never overwrite it with an old backup. Independent paired_backup.py verify and ip_forward_preflight.py must corroborate final state.

## CR-002 configuration
The successor checkout may contain a root-owned mode0600 `.env` with numeric ATOM_BUILD_BUDGET_SECONDS and ATOM_RUN_TIMEOUT_SECONDS (default3600, maximum7140); optional ATOM_LLM_TIMEOUT_SECONDS must be at least both budgets. Protected preflight captures only these keys, rejects invalid policy before writer fencing, and passes the captured values into candidate/private-env/api.env. Other credentials continue to come from existing protected sources. Do not commit this private file. Configuration changes require a new protected deployment/restart; they do not extend already-running leases.
Earlier fbfbb89 image is superseded by CR-001/CR-002 work and has not been deployed.
