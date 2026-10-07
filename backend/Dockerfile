FROM ghcr.io/astral-sh/uv:0.12.23 AS uv

FROM python:3.14.8-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=uv /uv /uvx /bin/

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

COPY . .

EXPOSE 8000

CMD ["uv", "run", "--no-sync", "sanic", "app.server:app", "--host", "0.0.0.0", "--port", "8000"]
