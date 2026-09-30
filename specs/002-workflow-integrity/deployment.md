# Deployment
Target: existing atom container and /atom/ reverse proxy on 159.75.231.98. Previous application revision a814938c422f9648c1a15ad3282b7cb3b76f8c84.

Backup completed 2026-09-30 before this release: /home/ubuntu/atom-backups/workflow002-20260930/ contains SQLite online backup, projects/published archive and previous revision. Image tag atom-demo:before-workflow002-20260930 preserved. Additive command_receipts table only; no existing records rewritten. Old image rollback can leave this unused table in place.

Deployed application revision cb50073bf01cdf3e9093aab1e2395ed5561790b2 on 2026-09-30. Image built before replacement; database showed zero running/queued runs. API and runtime health passed after startup, Linux runtime tests 4/4 passed, locked Pi 1905-file hash check passed in image build. Production bundle also passed controlled browser navigation/lost-response/stale-event regressions with zero page errors. Live production model workflow remains under verification; T007 stays open until its result is recorded.

Rollback: tag atom-demo:before-workflow002-20260930 as atom-demo:latest, then compose up -d --no-build with deploy/compose.reverse-proxy.yml. Verify /atom/api/health. Do not restore the database automatically or overwrite new user work.
