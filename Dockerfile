FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# UV_PROJECT_ENVIRONMENT points outside /app on purpose: docker-compose bind-mounts
# the repo over /app, which would shadow (and break) a venv living at /app/.venv.
ENV UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/simulator:/app

# Dependency layer: rebuilt only when pyproject.toml / uv.lock change.
# Not --frozen yet: uv.lock predates the requires-python bump and the `ml` group.
# Task 0 Step 8 regenerates the lock in-container, commits it, then switches
# this to `uv sync --frozen --all-groups` for reproducible builds.
COPY pyproject.toml uv.lock ./
RUN uv sync --all-groups

COPY . .
