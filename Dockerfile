# syntax=docker/dockerfile:1.7
#
# SynTrack container image (docs/CONTAINER_DESIGN.md).
# Three stages:
#   1) frontend-build  — node:22-alpine compiles the Svelte/Vite UI.
#   2) python-build    — resolves Python deps into an isolated venv via uv.
#   3) runtime         — slim final image, non-root syntrack user, the venv
#                        and the built UI copied in.

# ---------------------------------------------------------------------------
# 1) Frontend build
# ---------------------------------------------------------------------------
FROM node:22-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build
# → /app/frontend/dist

# ---------------------------------------------------------------------------
# 2) Python dep resolution into /opt/venv
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS python-build
WORKDIR /build
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir uv
COPY pyproject.toml README.md ./
COPY syntrack/ ./syntrack/
RUN uv venv /opt/venv --python python3.12
ENV VIRTUAL_ENV=/opt/venv PATH="/opt/venv/bin:$PATH"
RUN uv pip install --no-cache-dir .

# ---------------------------------------------------------------------------
# 3) Runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

# Unprivileged user. /home/syntrack exists for anything the venv may want to
# cache under $HOME (none today, but cheap insurance).
RUN groupadd -r syntrack && \
    useradd -r -g syntrack -u 1001 -m -d /home/syntrack -s /usr/sbin/nologin syntrack && \
    mkdir -p /config /data /cache /app && \
    chown syntrack:syntrack /config /data /cache /app

# Python venv (already contains the syntrack package installed in stage 2).
COPY --from=python-build --chown=syntrack:syntrack /opt/venv /opt/venv

# Built frontend assets.
COPY --from=frontend-build --chown=syntrack:syntrack /app/frontend/dist /app/frontend/dist

ENV PATH="/opt/venv/bin:$PATH" \
    SYNTRACK_CONFIG=/config/syntrack_config.yaml \
    SYNTRACK_FRONTEND_DIR=/app/frontend/dist \
    SYNTRACK_HOST=0.0.0.0 \
    SYNTRACK_PORT=8765 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
USER syntrack
EXPOSE 8765

# Healthcheck piggy-backs on /healthz. Startup is slow (~30-60 s for the pea
# dataset), so the first probe is delayed 60 s; Compose / Kubernetes users
# may want a longer start_period — see deploy/docker-compose.yml.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8765/healthz', timeout=2).status == 200 else 1)"

# Default command. `syntrack serve` reads config from SYNTRACK_CONFIG,
# binds SYNTRACK_HOST:SYNTRACK_PORT, and serves the API + UI.
ENTRYPOINT ["syntrack"]
CMD ["serve"]

# OCI image labels for the GHCR UI / provenance.
LABEL org.opencontainers.image.title="SynTrack" \
      org.opencontainers.image.description="Genome synteny visualisation tool (FastAPI + Svelte)." \
      org.opencontainers.image.source="https://github.com/kavonrtep/syntrack" \
      org.opencontainers.image.licenses="MIT"
