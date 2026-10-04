# Deployment — workspace performance

## Production release, 2026-10-04

Live source: `a621b9b968c326e87db5faef1ed962ff35627ec0`, clean root-owned `/home/ubuntu/atom-workspace-final`. Exact image: `sha256:58f9eeed2cf60664e69a3366d667656e064c1172363f0d0659a80bf9e17ed9b0`, matching the source revision label and `/atom/` frontend base. The earlier prepared `fbfbb89` image was superseded and never deployed. The original production release was `fd191e5c6ae5dc08865539f9b897473010b74943`.

The existing schema-18 protected forward transaction ran under `atom-deploy-workspace-a621b9b` and exited successfully. Its journal `/var/lib/atom-cutovers/a621b9b968c326e87db5faef1ed962ff35627ec0.forward-phase.json` was advanced from `awaiting_acceptance` to `accepted` after live tests. A post-acceptance `ip_forward_preflight.py` returned `current_generation_verified`, image and revision above, six exact container IDs, 80 active origins and Caddy SHA-256 `b4347fd658c690a533fb42c4bea634608f7bc8bb7fd74d25b811aa8219320011`.

The active data directory is `/var/backups/atom-cutovers/forward-candidate-a621b9b968c3` (the directory name reflects the transaction's candidate generation; it is **live data**, not a disposable backup). It remains intact. Public port 20073 returned certificate-verified HTTP 200 with the pre-release HTML SHA-256 `4a3b8558d8863990a5fc323f1bbf30895d9f36430c49a738451a9afca582a980`; isolated preview returned HTTP 200. The six services, origin/certificate timers and ingress were healthy.

## User-requested no-backup handling

The protected transaction had already produced `/var/backups/atom-cutovers/forward-pre-a621b9b968c3` before the user instructed us not to keep a backup in this test environment. After acceptance, an exact-path, root-ownership and no-symlink check removed only that temporary pre-cutover directory. The filesystem reported 192,036,864 bytes freed. The active candidate directory was checked intact, and the current-generation preflight passed again after deletion. No further backup was created. A future cutover must honor this instruction explicitly; the current protected forward operator creates a backup by default and must not be rerun unchanged under a no-backup instruction.

## Recovery boundary

The release journal is accepted and may be audited. The previous-generation temporary backup has been removed by user request, so rollback to the former data generation is unavailable through it. Preserve the active candidate data. Existing `deploy/ip_forward_recovery.py` guards against restoring older data over durable writes; do not invoke source restoration for this accepted release. The code/image can be rebuilt from the exact Git revision, but that is distinct from restoring old project data.

## Generation configuration

The root-owned mode-0600 `/home/ubuntu/atom-workspace-final/.env` sets `ATOM_BUILD_BUDGET_SECONDS=3600` and `ATOM_RUN_TIMEOUT_SECONDS=3600`; effective model timeout inherits this budget. The supported maximum is 7140 seconds plus broker cleanup allowance, validated before a future cutover. Credentials remain in protected configuration and are not committed. Configuration changes require a new safe deployment/restart and do not extend already-running leases.
