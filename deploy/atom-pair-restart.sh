#!/usr/bin/env bash
set -euo pipefail

# The broker shares the API container's network namespace. Restarting the API
# alone leaves a running broker in the old namespace, so always stop the broker
# before changing the API namespace and start it again afterwards.
exec 9>/run/lock/atom-pair-restart.lock
flock -n 9 || { echo 'Atom pair restart already in progress' >&2; exit 1; }

api=atom-candidate
broker=atom-candidate-broker
docker inspect "$api" "$broker" >/dev/null

if [[ "$(docker inspect -f '{{.State.Running}}' "$api")" == true ]]; then
  active=$(docker exec "$api" /app/backend/.venv/bin/python -c \
    'import sqlite3; c=sqlite3.connect("file:/data/atom.db?mode=ro", uri=True); print(c.execute("select count(*) from projects where active_run_id is not null").fetchone()[0])')
  if [[ "$active" != 0 ]]; then
    echo "Refusing restart: $active projects have active runs" >&2
    exit 1
  fi
fi

if [[ "$(docker inspect -f '{{.State.Running}}' "$broker")" == true ]]; then
  docker stop "$broker" >/dev/null
fi
if [[ "$(docker inspect -f '{{.State.Running}}' "$api")" == true ]]; then
  docker restart "$api" >/dev/null
else
  docker start "$api" >/dev/null
fi
docker start "$broker" >/dev/null

for ((attempt = 0; attempt < 90; attempt++)); do
  api_health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$api")
  broker_health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$broker")
  if [[ "$api_health" == healthy && "$broker_health" == healthy ]]; then
    echo 'Atom API and broker are healthy'
    exit 0
  fi
  sleep 2
done
echo "Atom pair did not become healthy: API=$api_health broker=$broker_health" >&2
exit 1
