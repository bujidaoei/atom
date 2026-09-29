# Single-box image: nginx serves the SPA, uvicorn serves the API, and the
# vendored WorkDude agent runtime runs as a Node sidecar. Supervisor keeps
# all three alive.

# ---------------------------------------------------------------- frontend
FROM node:24-bookworm-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
ARG VITE_BASE=/
ENV VITE_BASE=$VITE_BASE
RUN npm run build

# ----------------------------------------------------------- agent runtime
# The runtime tree is copied verbatim from WorkDude. `verify:pi-source`
# re-checks every vendored Pi file against pi-source.lock.json, so a corrupt
# or tampered copy fails the build instead of shipping.
FROM node:24-bookworm-slim AS runtime
WORKDIR /runtime
COPY runtime/package.json runtime/package-lock.json ./
RUN npm ci
COPY runtime/ ./
RUN node scripts/verify-pi-source.mjs \
    && node -e "import('./packages/agent-runtime/src/pi-runtime-loader.mjs').then(()=>console.log('pi gateway bundle loads'))"

# ------------------------------------------------------------------ server
FROM python:3.12-slim-bookworm

RUN printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d && chmod +x /usr/sbin/policy-rc.d \
    && apt-get update \
    && apt-get install -y --no-install-recommends nginx supervisor ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /etc/nginx/sites-enabled/default

# The agent runtime is TypeScript on Node 24; reuse the official binary
# rather than apt's older build.
COPY --from=runtime /usr/local/bin/node /opt/node/bin/node
COPY --from=runtime /usr/local/lib/node_modules /opt/node/lib/node_modules
ENV PATH="/opt/node/bin:${PATH}"

COPY --from=ghcr.io/astral-sh/uv:0.11.14 /uv /uvx /bin/

WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev
COPY backend/app ./app

COPY --from=runtime /runtime /app/runtime
COPY --from=web /web/dist /usr/share/nginx/html
COPY deploy/nginx.conf /etc/nginx/nginx.conf
COPY deploy/supervisord.conf /etc/supervisor/supervisord.conf

ENV ATOM_DATA_DIR=/data \
    ATOM_DB_PATH=/data/atom.db \
    ATOM_RUNTIME_URL=http://127.0.0.1:8721 \
    ATOM_RUNTIME_PORT=8721 \
    WORKDUDE_PI_CACHE_REPOSITORY_ROOT=/app/runtime \
    PI_OFFLINE=1

EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1/api/health || exit 1

CMD ["supervisord", "-c", "/etc/supervisor/supervisord.conf"]
