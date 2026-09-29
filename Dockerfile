FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
ARG VITE_BASE=/
ENV VITE_BASE=$VITE_BASE
RUN npm run build

FROM node:22-bookworm-slim AS pi
WORKDIR /runtime
COPY runtime/package.json runtime/package-lock.json ./
RUN npm ci --omit=dev
COPY runtime/run.mjs ./

FROM python:3.12-slim-bookworm
RUN printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d && chmod +x /usr/sbin/policy-rc.d \
    && apt-get update \
    && apt-get install -y --no-install-recommends nginx supervisor ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /etc/nginx/sites-enabled/default

COPY --from=ghcr.io/astral-sh/uv:0.11.14 /uv /uvx /bin/
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev
COPY backend/app ./app
COPY --from=web /usr/local/bin/node /opt/node/bin/node
COPY --from=web /usr/local/lib /opt/node/lib
COPY --from=pi /runtime /app/runtime
COPY --from=web /web/dist /usr/share/nginx/html
COPY deploy/nginx.conf /etc/nginx/nginx.conf
COPY deploy/supervisord.conf /etc/supervisor/supervisord.conf

ENV ATOM_DB_PATH=/data/atom.db \
    PATH="/opt/node/bin:${PATH}" \
    LD_LIBRARY_PATH="/opt/node/lib" \
    ATOM_PI_ENTRY=/app/runtime/run.mjs \
    ATOM_PI_NODE=/opt/node/bin/node \
    PI_OFFLINE=1
EXPOSE 80
CMD ["supervisord", "-c", "/etc/supervisor/supervisord.conf"]
