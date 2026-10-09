# ShipX backend container image — runs on Azure Container Apps (the Lambda-free
# compute path selected by CLOUD_PROVIDER=azure). One image, three workloads,
# chosen by the entrypoint command: `api` (HTTP), `worker` (Service Bus consumer),
# `job` (scheduled cron), plus `migrate`. AWS keeps using the Lambda zip path and
# does not use this image.
#
# Build:  docker build -t shipx-backend .
# Run:    docker run -p 8080:8080 shipx-backend api
#         docker run shipx-backend worker --queue sms
#         docker run shipx-backend job --job release_expiry

# ---- Builder: resolve the locked deps into a venv -------------------------------
FROM python:3.13-slim AS builder

# uv for fast, lockfile-faithful installs (uv.lock is the source of truth).
# Pinned to the uv that produces uv.lock locally + in CI, so the lock format matches.
COPY --from=ghcr.io/astral-sh/uv:0.12.24 /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app

# Only the dependency manifests, so the layer caches until deps change.
COPY pyproject.toml uv.lock ./

# Runtime deps only: project `dependencies` + azure SDKs + the container WSGI
# stack + alembic (layer group, for the migrate workload). No dev/test tooling.
RUN uv sync --frozen --no-install-project --no-dev \
    --extra azure --extra container --group layer

# ---- Runtime: slim image with just the venv + app source ------------------------
FROM python:3.13-slim AS runtime

# Non-root runtime user.
RUN groupadd --system shipx && useradd --system --gid shipx --home /app shipx

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Handlers import both `services.X` and bare top-level packages (e.g. `metering`),
    # so both roots must be importable — mirrors the test/local PYTHONPATH=.:services.
    PYTHONPATH="/app:/app/services" \
    PORT=8080

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv

# Application code the workloads import at runtime.
COPY shared/ ./shared/
COPY services/ ./services/
COPY scripts/ ./scripts/
COPY migrations/ ./migrations/
COPY docker-entrypoint.sh ./docker-entrypoint.sh

RUN chmod +x docker-entrypoint.sh && chown -R shipx:shipx /app

USER shipx

EXPOSE 8080

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["api"]
