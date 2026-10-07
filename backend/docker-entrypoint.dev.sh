#!/bin/sh
set -eu

uv run --no-sync alembic upgrade head
exec uv run --no-sync sanic app.server:app --dev --host 0.0.0.0 --port 8000
