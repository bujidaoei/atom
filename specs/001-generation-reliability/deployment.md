# Deployment progress

Target: existing Atom container on 159.75.231.98, /atom/ reverse proxy. Existing repository: /home/ubuntu/atom. Existing revision: 95c163d2282d87db77fe26fede0fdc2bf83f064c.

Backup target: /home/ubuntu/atom-backups/reliability-20260930. Old image tag: atom-demo:before-reliability-20260930. SQLite backup uses SQLite online backup API; project/published files archived separately. No database migration required.

Application revision 8107852cacc239c405dbb6eb5f5995a1404147d4 was pushed to codex/001-generation-reliability and deployed on 2026-09-30. Backup completed before replacement. Image manifest: sha256:a9ebce6d584c74d4d754f0c5f718f2932dc07e7b9bdaeb9ae5b7322adce3410d. Public /atom/api/health returns {"ok":true,"runtime":true}. All four runtime tests passed inside the Linux production container, including real Pi recovery and process-tree cancellation. Pi source verification and frontend build passed in Docker.

Release encountered a single-branch Git fetch configuration and intermittent SSH banner timeouts. Explicit ref fetch plus detached tested revision resolved checkout; the index and worktree were checked against the target before continuing. Existing container continued serving until the new image was built. Health polling saw transient 502 during replacement, then recovered. No database migration or user-data replacement was performed.

Final application revision: a814938c422f9648c1a15ad3282b7cb3b76f8c84. Final image manifest: sha256:30951f1e433b1bd97eb5bd94fe1e68f594a74c6ba4725157fba44e7465154b2d. Rebuilt and deployed successfully; health and all four Linux runtime tests passed again. Production scenarios and limitations are documented in evidence.md: final browser 12/12, 9/9, 10/10 after one explicit snake repair. Actual UI acceptance saved a new 12/12 record. Publish/unpublish smoke returned 200/404. Initial failures remain recorded; this release does not guarantee all generated apps succeed on their first attempt.

Status: deployed and verification completed. T012 and T014 are complete for their implemented scope. Later evidence-only commits do not change the deployed application binaries.

Rollback: tag atom-demo:before-reliability-20260930 as atom-demo:latest and run `docker compose -f docker-compose.yml -f deploy/compose.reverse-proxy.yml up -d --no-build`. Verify /atom/api/health. Do not restore data automatically; existing schema is unchanged.
