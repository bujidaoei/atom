# Deployment progress

Target: existing Atom container on 159.75.231.98, /atom/ reverse proxy. Existing repository: /home/ubuntu/atom. Existing revision: 95c163d2282d87db77fe26fede0fdc2bf83f064c.

Backup target: /home/ubuntu/atom-backups/reliability-20260930. Old image tag: atom-demo:before-reliability-20260930. SQLite backup uses SQLite online backup API; project/published files archived separately. No database migration required.

Status: backup/deployment verification in progress; T012 remains open.

Rollback: tag atom-demo:before-reliability-20260930 as atom-demo:latest and run `docker compose -f docker-compose.yml -f deploy/compose.reverse-proxy.yml up -d --no-build`. Verify /atom/api/health. Do not restore data automatically; existing schema is unchanged.
