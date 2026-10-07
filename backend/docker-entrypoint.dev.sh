#!/bin/sh
set -eu

uv run --no-sync python manage.py migrate
exec uv run --no-sync python manage.py runserver 0.0.0.0:8000
