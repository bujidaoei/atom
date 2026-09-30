# Deployment
Target: existing atom container and /atom/ reverse proxy on 159.75.231.98. Previous application revision a814938c422f9648c1a15ad3282b7cb3b76f8c84.

Backup completed 2026-09-30 before this release: /home/ubuntu/atom-backups/workflow002-20260930/ contains SQLite online backup, projects/published archive and previous revision. Image tag atom-demo:before-workflow002-20260930 preserved. Additive command_receipts table only; no existing records rewritten. Old image rollback can leave this unused table in place.

Initial application revision cb50073bf01cdf3e9093aab1e2395ed5561790b2 deployed on 2026-09-30. Image built before replacement; database showed zero running/queued runs. API and runtime health passed after startup, Linux runtime tests 4/4 passed, locked Pi 1905-file hash check passed in image build. Production bundle also passed controlled browser navigation/lost-response/stale-event regressions with zero page errors. Subsequent font discovery led to the final revision below.

Final application revision 8e1ea6c6ac4fea229630b5c7dbcb647b24c43588 additionally bundles fonts after production browser tracing found the blocking external stylesheet. Rebuild/deploy again checked zero active runs, health and Linux 4/4 runtime tests. Production fault suite passed with third-party font routes held indefinitely; separate cold browser startup reached DOMContentLoaded in 2.778 seconds with no external font requests (single observation, not a latency SLA).

Production live workflow and final 21/21 generated contract checks passed, both projects ready, no page errors/mobile overflow. See evidence.md for the initial mobile failure and real AI repair. Later evidence-only commits do not change the application image. All production generation/revise operations used isolated test accounts; original user projects were not edited.

Rollback: tag atom-demo:before-workflow002-20260930 as atom-demo:latest, then compose up -d --no-build with deploy/compose.reverse-proxy.yml. Verify /atom/api/health. Do not restore the database automatically or overwrite new user work.
