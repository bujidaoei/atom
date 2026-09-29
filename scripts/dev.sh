#!/usr/bin/env bash
# Starts the agent runtime sidecar and the API for local development.
# Logs land in .logs/. Ctrl-C stops both.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
logs="$root/.logs"
mkdir -p "$logs"

if [[ ! -f "$root/backend/.env" ]]; then
  echo "Missing backend/.env. Copy .env.example and fill in the gateway key." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source "$root/backend/.env"
set +a

export WORKDUDE_PI_CACHE_REPOSITORY_ROOT="$root/runtime"
export ATOM_RUNTIME_PORT="${ATOM_RUNTIME_PORT:-8721}"

cleanup() {
  jobs -p | xargs -r kill 2>/dev/null || true
}
trap cleanup EXIT INT TERM

(cd "$root/runtime" && node --import tsx src/server.ts) >"$logs/runtime.log" 2>&1 &
echo "runtime  -> http://127.0.0.1:${ATOM_RUNTIME_PORT}"

(cd "$root/backend" && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000) \
  >"$logs/api.log" 2>&1 &
echo "api      -> http://127.0.0.1:8000"

echo "logs in $logs"
wait
