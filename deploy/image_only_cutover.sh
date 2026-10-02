#!/usr/bin/env bash
# Schema-preserving image switch for the single-box test deployment.
# No database copy or migration occurs. Keep the stopped prior pair for rollback.
set -Eeuo pipefail
umask 077

if (( $# != 3 )); then
  echo 'usage: image_only_cutover.sh REVISION IMAGE_ID CLEAN_SOURCE' >&2
  exit 2
fi
revision=$1
image=$2
source=$3
short=${revision:0:12}
old_api="atom-before-${short}"
old_broker="atom-broker-before-${short}"
data=/home/ubuntu/atom-staging/94bfcd7/data
broker_data=/home/ubuntu/atom-staging/94bfcd7/broker
private=$(mktemp -d /run/atom-image-cutover.XXXXXXXX)
phase=before_stop
finished=0

recover() {
  local code=$?
  trap - ERR EXIT
  if (( finished == 1 )); then
    rm -rf -- "$private"
    return 0
  fi
  echo "image cutover failed in phase ${phase}; restoring prior pair" >&2
  if [[ $phase != before_stop ]]; then
    if docker inspect "$old_broker" >/dev/null 2>&1; then
      docker rm -f atom-candidate-broker >/dev/null 2>&1 || true
      docker rename "$old_broker" atom-candidate-broker || true
    fi
    if docker inspect "$old_api" >/dev/null 2>&1; then
      docker rm -f atom-candidate >/dev/null 2>&1 || true
      docker rename "$old_api" atom-candidate || true
    fi
    docker start atom-candidate >/dev/null 2>&1 || true
    docker start atom-candidate-broker >/dev/null 2>&1 || true
  fi
  rm -rf -- "$private"
  exit "$code"
}
trap recover ERR EXIT

exec 9>/run/lock/atom-image-cutover.lock
flock -n 9
[[ $revision =~ ^[0-9a-f]{40}$ && $image =~ ^sha256:[0-9a-f]{64}$ ]]
[[ $source == /* && -f $source/deploy/protected_cutover.py ]]
! docker inspect "$old_api" >/dev/null 2>&1
! docker inspect "$old_broker" >/dev/null 2>&1

preflight=$(python3 "$source/deploy/protected_cutover.py" preflight \
  --config /etc/atom/protected-cutover.json \
  --source "$source" --revision "$revision" --image-id "$image")
backup_dir=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["backupDirectory"])' <<<"$preflight")
[[ $backup_dir == /* && ! -e $backup_dir ]]
docker inspect atom-candidate > "$private/api.inspect.json"
docker inspect atom-candidate-broker > "$private/broker.inspect.json"
python3 - "$private" "$image" <<'PY'
import json
from pathlib import Path
import sys

directory, image = Path(sys.argv[1]), sys.argv[2]
for name in ('api', 'broker'):
    env = json.loads((directory / f'{name}.inspect.json').read_text('utf-8'))[0]['Config']['Env']
    if name == 'broker':
        assert sum(row.startswith('ATOM_BROKER_IMAGE=') for row in env) == 1
        env = [('ATOM_BROKER_IMAGE=' + image) if row.startswith('ATOM_BROKER_IMAGE=') else row
               for row in env]
    assert all('\n' not in row and '\r' not in row for row in env)
    path = directory / f'{name}.env'
    path.write_text('\n'.join(env) + '\n', encoding='utf-8')
    path.chmod(0o600)
PY

phase=stopping
docker stop atom-candidate-broker >/dev/null
docker stop atom-candidate >/dev/null
phase=backing_up
install -d -m 0700 -- "$backup_dir"
python3 - "$data/atom.db" "$backup_dir/atom.db" "$broker_data/registry.db" "$backup_dir/registry.db" <<'PY'
import sqlite3
import sys

for source, destination, expected in zip(sys.argv[1::2], sys.argv[2::2], (10, 3), strict=True):
    live = sqlite3.connect(f'file:{source}?mode=ro', uri=True, timeout=10)
    copy = sqlite3.connect(destination)
    try:
        live.backup(copy, pages=256, sleep=.05)
        if (copy.execute('PRAGMA user_version').fetchone()[0] != expected
                or copy.execute('PRAGMA integrity_check').fetchall() != [('ok',)]
                or copy.execute('PRAGMA foreign_key_check').fetchall()):
            raise RuntimeError('cutover_backup_invalid')
    finally:
        copy.close()
        live.close()
PY
tar -C "$data" -cf "$backup_dir/data.tar" .
tar -C "$broker_data" -cf "$backup_dir/broker.tar" .
tar -tf "$backup_dir/data.tar" >/dev/null
tar -tf "$backup_dir/broker.tar" >/dev/null
(cd "$backup_dir" && sha256sum atom.db registry.db data.tar broker.tar > sha256sums.txt && sha256sum -c sha256sums.txt >/dev/null)
docker rename atom-candidate "$old_api"
docker rename atom-candidate-broker "$old_broker"
phase=creating
docker create --name atom-candidate --restart unless-stopped \
  --log-driver local --log-opt max-size=10m --log-opt max-file=3 \
  --network new-api_new-api-network -p 127.0.0.1:18081:80 \
  --env-file "$private/api.env" -v "$data:/data" "$image" >/dev/null
docker create --name atom-candidate-broker --restart unless-stopped \
  --log-driver local --log-opt max-size=10m --log-opt max-file=3 \
  --network container:atom-candidate --read-only --tmpfs /tmp:size=32m \
  --security-opt no-new-privileges --env-file "$private/broker.env" \
  -v "$broker_data:/broker" -v /var/run/docker.sock:/var/run/docker.sock \
  -v /usr/bin/docker:/usr/bin/docker:ro \
  "$image" /app/backend/.venv/bin/python -m app.sandbox >/dev/null
phase=starting
docker start atom-candidate >/dev/null
docker start atom-candidate-broker >/dev/null
for (( attempt=0; attempt<90; attempt++ )); do
  api_health=$(docker inspect atom-candidate --format '{{.State.Health.Status}}')
  broker_health=$(docker inspect atom-candidate-broker --format '{{.State.Health.Status}}')
  if [[ $api_health == healthy && $broker_health == healthy ]]; then break; fi
  sleep 2
done
[[ $api_health == healthy && $broker_health == healthy ]]
python3 - "$data/atom.db" "$broker_data/registry.db" <<'PY'
import sqlite3
import sys

for path, expected in zip(sys.argv[1:], (10, 3), strict=True):
    db = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    try:
        assert db.execute('PRAGMA user_version').fetchone()[0] == expected
        assert db.execute('PRAGMA quick_check').fetchall() == [('ok',)]
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    finally:
        db.close()
PY
[[ $(docker inspect atom-candidate --format '{{.Image}}') == "$image" ]]
[[ $(docker inspect atom-candidate-broker --format '{{.Image}}') == "$image" ]]
finished=1
echo "image cutover complete: revision=$revision image=$image schema=10/3"
