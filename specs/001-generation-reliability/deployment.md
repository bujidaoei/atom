# Deployment progress

Target: existing Atom container on 159.75.231.98, /atom/ reverse proxy. Existing repository: /home/ubuntu/atom. Existing revision: 95c163d2282d87db77fe26fede0fdc2bf83f064c.

Backup target: /home/ubuntu/atom-backups/reliability-20260930. Old image tag: atom-demo:before-reliability-20260930. SQLite backup uses SQLite online backup API; project/published files archived separately. No database migration required.

Application revision 8107852cacc239c405dbb6eb5f5995a1404147d4 was pushed to codex/001-generation-reliability and deployed on 2026-09-30. Backup completed before replacement. Image manifest: sha256:a9ebce6d584c74d4d754f0c5f718f2932dc07e7b9bdaeb9ae5b7322adce3410d. Public /atom/api/health returns {"ok":true,"runtime":true}. All four runtime tests passed inside the Linux production container, including real Pi recovery and process-tree cancellation. Pi source verification and frontend build passed in Docker.

Release encountered a single-branch Git fetch configuration and intermittent SSH banner timeouts. Explicit ref fetch plus detached tested revision resolved checkout; the index and worktree were checked against the target before continuing. Existing container continued serving until the new image was built. Health polling saw transient 502 during replacement, then recovered. No database migration or user-data replacement was performed.

Status: production generation/browser smoke in progress; T012 remains open.

Rollback: tag atom-demo:before-reliability-20260930 as atom-demo:latest and run `docker compose -f docker-compose.yml -f deploy/compose.reverse-proxy.yml up -d --no-build`. Verify /atom/api/health. Do not restore data automatically; existing schema is unchanged.
