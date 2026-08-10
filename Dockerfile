FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# UV_PROJECT_ENVIRONMENT points outside /app on purpose: docker-compose bind-mounts
# the repo over /app, which would shadow (and break) a venv living at /app/.venv.
ENV UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/simulator:/app/ml:/app/dashboard:/app

# Dependency layer: rebuilt only when pyproject.toml / uv.lock change.
# --frozen makes the build fail loudly on a lock/manifest mismatch rather than
# silently re-resolving, so images stay reproducible. Regenerate the lock with
#   docker compose run --rm sim uv lock
# whenever pyproject.toml changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --all-groups

COPY . .
