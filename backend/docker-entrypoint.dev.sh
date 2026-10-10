#!/bin/sh
set -eu

# The image's /app/.venv is hidden by the source bind mount, so the mounted
# backend_venv volume is what actually runs. Reconcile it with uv.lock on every
# start; otherwise adding a dependency to pyproject.toml never lands in the
# long-lived volume and imports fail until the volume is manually removed.
uv sync --locked

uv run --no-sync alembic upgrade head
exec uv run --no-sync sanic app.server:app --dev --host 0.0.0.0 --port 8000
