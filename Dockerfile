# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY src ./src

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---- Tailwind CSS (standalone binary, no Node runtime required) ----
FROM debian:bookworm-slim AS tailwind-builder

# Download tailwindcss standalone binary (linux x64; adjust for arm64 if needed)
RUN apt-get update -qq && apt-get install -y -qq curl ca-certificates && \
    curl -fsSL \
      "https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-linux-x64" \
      -o /usr/local/bin/tailwindcss && \
    chmod +x /usr/local/bin/tailwindcss

WORKDIR /app
COPY src/daddy_bot/web/templates ./src/daddy_bot/web/templates
# Minimal tailwind config to scan all templates
RUN printf 'module.exports={content:["./src/daddy_bot/web/templates/**/*.html"],theme:{extend:{}},plugins:[]}' \
      > tailwind.config.js && \
    printf '@tailwind base;\n@tailwind components;\n@tailwind utilities;\n' \
      > input.css && \
    tailwindcss -i input.css \
      -o src/daddy_bot/web/static/tailwind.css \
      --minify

# ---- Runtime ----
FROM python:3.11-slim AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --system app && useradd --system --gid app --create-home --home-dir /app app

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY src ./src
COPY assets ./assets
# Copy compiled Tailwind CSS
COPY --from=tailwind-builder /app/src/daddy_bot/web/static/tailwind.css \
     /app/src/daddy_bot/web/static/tailwind.css

RUN mkdir -p /app/data && chown -R app:app /app

USER app

CMD ["daddy-bot"]
