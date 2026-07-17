# 100.Nexus — mypage 영역 (auth + account + invention CRUD/metadata).
# DRO 와 분리된 별도 컨테이너 (분리 안 A — `.docs/Temp/EXTERNAL_API_TEMP_REVIEW/02-unit-split-review.md`).
# chain runtime 의존 없음 — DRO 의 가벼운 버전.

FROM python:3.14-slim AS production

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

COPY shared/ /shared/

COPY 100.Nexus/pyproject.toml 100.Nexus/uv.lock* ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY 100.Nexus/src/ src/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

CMD exec uv run uvicorn src.main:app --host 0.0.0.0 --port "${PORT}"
