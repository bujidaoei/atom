#!/usr/bin/env bash
#
# One-shot deployment for a fresh Ubuntu box.
#
#   curl -fsSL https://raw.githubusercontent.com/bujidaoei/atom/main/deploy/server-setup.sh | bash -s -- <API_KEY>
#
# or, after cloning:
#
#   sudo bash deploy/server-setup.sh <API_KEY>
#
# Port 80 is often already taken, so this defaults to 8080. Override with
# ATOM_HTTP_PORT=9000 bash deploy/server-setup.sh ...

set -euo pipefail

API_KEY="${1:-${ATOM_LLM_API_KEY:-}}"
HTTP_PORT="${ATOM_HTTP_PORT:-8080}"
REPO="${ATOM_REPO:-https://github.com/bujidaoei/atom.git}"
TARGET="${ATOM_DIR:-$HOME/atom}"

# Set ATOM_PROXY_NETWORK to sit behind an existing reverse proxy on a subpath
# instead of publishing a host port. See deploy/compose.reverse-proxy.yml.
PROXY_NETWORK="${ATOM_PROXY_NETWORK:-}"
BASE_PATH="${ATOM_BASE_PATH:-/atom}"

if [[ -z "$API_KEY" ]]; then
  echo "usage: bash deploy/server-setup.sh <AI_GATEWAY_API_KEY>" >&2
  exit 1
fi

say() { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }

# Every external dependency this build needs, measured up front.
#
# Networks differ wildly in which hosts they can reach quickly: on the box
# this was written for, git over HTTPS was fine while raw.githubusercontent
# hung outright and pythonhosted crawled at 3.5 kB/s. Discovering that one
# Docker layer at a time costs a full rebuild per finding, so check first
# and print a table.
preflight() {
  say "Checking network paths"
  printf '    %-42s %10s %12s\n' TARGET STATUS SPEED
  local failed=0
  local target url
  for target in \
    "github.com|https://github.com/bujidaoei/atom.git/info/refs?service=git-upload-pack" \
    "registry.npmjs.org|https://registry.npmjs.org/tsx" \
    "docker registry|https://registry-1.docker.io/v2/"
  do
    url="${target#*|}"
    if probe "${target%%|*}" "$url"; then :; else failed=1; fi
  done
  [[ -n "$APT_MIRROR"  ]] && probe "apt mirror"  "http://${APT_MIRROR}/debian/"
  [[ -n "$PYPI_INDEX"  ]] && probe "pypi index"  "${PYPI_INDEX}/uvloop/"
  if [[ $failed -eq 1 ]]; then
    say "A required host is unreachable. Fix connectivity before building."
    exit 1
  fi
}

probe() {
  local label=$1 url=$2 out code speed
  out=$(curl -fsS --max-time 12 -o /dev/null \
        -w '%{http_code} %{speed_download}' "$url" 2>/dev/null) || {
    printf '    %-42s %10s %12s\n' "$label" UNREACHABLE -
    return 1
  }
  code=${out%% *}; speed=${out##* }
  printf '    %-42s %10s %10.0f B/s\n' "$label" "$code" "$speed"
  return 0
}

# The default Debian mirror is unusably slow from some clouds. Prefer the
# provider's internal mirror when one answers quickly.
detect_apt_mirror() {
  for candidate in mirrors.tencentyun.com mirrors.cloud.aliyuncs.com; do
    if curl -fsS --max-time 3 -o /dev/null "http://${candidate}/debian/" 2>/dev/null; then
      echo "$candidate"
      return
    fi
  done
  echo ""
}

detect_pypi_index() {
  for candidate in \
    http://mirrors.tencentyun.com/pypi/simple \
    https://mirrors.cloud.aliyuncs.com/pypi/simple
  do
    if curl -fsS --max-time 3 -o /dev/null "$candidate/" 2>/dev/null; then
      echo "$candidate"
      return
    fi
  done
  echo ""
}

# ---------------------------------------------------------------- docker
if ! command -v docker >/dev/null 2>&1; then
  say "Installing Docker"
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER" || true
fi

if ! docker compose version >/dev/null 2>&1; then
  say "Installing the Docker Compose plugin"
  sudo apt-get update -qq
  sudo apt-get install -y -qq docker-compose-plugin
fi

DOCKER="docker"
docker info >/dev/null 2>&1 || DOCKER="sudo docker"

# ----------------------------------------------------------------- source
if [[ -d "$TARGET/.git" ]]; then
  say "Updating $TARGET"
  git -C "$TARGET" fetch --depth 1 origin main
  git -C "$TARGET" reset --hard origin/main
  git -C "$TARGET" clean -fd -e .env
else
  if [[ -e "$TARGET" ]]; then
    # An earlier deployment may have left a bare compose directory here.
    # Keep it rather than deleting someone's .env by surprise.
    backup="${TARGET}.backup-$(date +%Y%m%d%H%M%S)"
    say "Moving the existing $TARGET aside to $backup"
    mv "$TARGET" "$backup"
  fi
  say "Cloning into $TARGET"
  git clone --depth 1 "$REPO" "$TARGET"
fi
cd "$TARGET"

# The vendored Pi tree is hash-locked; a mangled checkout must fail here
# rather than at the first agent turn.
say "Verifying the vendored agent runtime"
if command -v node >/dev/null 2>&1; then
  (cd runtime && node scripts/verify-pi-source.mjs)
else
  echo "    node not installed on the host; the image build will verify instead"
fi

# ------------------------------------------------------------------- env
say "Writing .env"
cat > .env <<EOF
ATOM_SECRET=$(openssl rand -hex 32)
ATOM_DATA_DIR=/data
ATOM_DB_PATH=/data/atom.db
ATOM_LLM_BASE_URL=${ATOM_LLM_BASE_URL:-https://ai-gateway.skg.com/v1}
ATOM_LLM_API_KEY=${API_KEY}
ATOM_LLM_MODEL=${ATOM_LLM_MODEL:-deepseek-v4.1-flash}
ATOM_LLM_PLANNING_MODEL=${ATOM_LLM_PLANNING_MODEL:-deepseek-v4.1-flash}
ATOM_RUNTIME_URL=http://127.0.0.1:8721
ATOM_RUNTIME_TOKEN=$(openssl rand -hex 16)
ATOM_COOKIE_SECURE=false
ATOM_STARTING_CREDITS=200
ATOM_HTTP_PORT=${HTTP_PORT}
APT_MIRROR=${APT_MIRROR:-$(detect_apt_mirror)}
PYPI_INDEX=${PYPI_INDEX:-$(detect_pypi_index)}
EOF

COMPOSE_ARGS=(-f docker-compose.yml)
if [[ -n "$PROXY_NETWORK" ]]; then
  COMPOSE_ARGS+=(-f deploy/compose.reverse-proxy.yml)
  cat >> .env <<EOF
ATOM_PROXY_NETWORK=${PROXY_NETWORK}
ATOM_COOKIE_PATH=${BASE_PATH}
VITE_BASE=${BASE_PATH}/
EOF
  HEALTH_URL="http://127.0.0.1${BASE_PATH}/api/health"
else
  HEALTH_URL="http://127.0.0.1:${HTTP_PORT}/api/health"
fi
chmod 600 .env

# ----------------------------------------------------------------- build
say "Building and starting (first build pulls Node 24 and Python 3.12, give it a few minutes)"
$DOCKER compose "${COMPOSE_ARGS[@]}" up -d --build

# ---------------------------------------------------------------- verify
say "Waiting for the health check at ${HEALTH_URL}"
for _ in $(seq 1 60); do
  health=$(curl -fsS --max-time 5 "$HEALTH_URL" 2>/dev/null || true)
  if [[ -n "$health" ]]; then
    echo "    $health"
    case "$health" in
      *'"runtime":true'*)
        ip=$(curl -fsS --max-time 5 ifconfig.me 2>/dev/null || echo "<server-ip>")
        if [[ -n "$PROXY_NETWORK" ]]; then
          say "Up at http://${ip}${BASE_PATH}/"
        else
          say "Up at http://${ip}:${HTTP_PORT}/"
        fi
        exit 0
        ;;
    esac
  fi
  sleep 5
done

say "Did not come up cleanly. Recent logs:"
$DOCKER compose "${COMPOSE_ARGS[@]}" logs --tail 60
exit 1
