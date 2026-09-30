# Deployment
Target: existing atom container and /atom/ reverse proxy on 159.75.231.98. Previous application revision a814938c422f9648c1a15ad3282b7cb3b76f8c84.

Backup completed 2026-09-30 before this release: /home/ubuntu/atom-backups/workflow002-20260930/ contains SQLite online backup, projects/published archive and previous revision. Image tag atom-demo:before-workflow002-20260930 preserved. Additive command_receipts table only; no existing records rewritten. Old image rollback can leave this unused table in place.

Publish gate: local tests and real UI workflow evidence; verify no active user jobs before replacing container; build image before replacement. Deployment/production smoke not yet completed; T007 remains open.

Rollback: tag atom-demo:before-workflow002-20260930 as atom-demo:latest, then compose up -d --no-build with deploy/compose.reverse-proxy.yml. Verify /atom/api/health. Do not restore the database automatically or overwrite new user work.
