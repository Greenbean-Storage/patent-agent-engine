# Single production stage — development target / hot reload 폐기.
FROM python:3.14-slim AS production

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY shared/ /shared/

COPY 400.CM/pyproject.toml 400.CM/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY 400.CM/src ./src

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# 포트는 compose 가 $PORT env 로 주입 (topology.yaml → .env.topology 가 SoT).
CMD exec uv run uvicorn src.main:app --host 0.0.0.0 --port "${PORT}"
