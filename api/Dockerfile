# --- build: install deps into a venv with uv ---
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY sql ./sql
RUN uv sync --frozen --no-dev

# --- runtime: slim image, non-root user ---
FROM python:3.12-slim
RUN useradd --create-home appuser
WORKDIR /app
COPY --from=build --chown=appuser /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER appuser
# Render/Koyeb inject $PORT; default to 8000 locally.
CMD ["sh", "-c", "uvicorn circulariq.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
