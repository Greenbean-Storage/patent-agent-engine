# production + mock 멀티스테이지 — compose 의 build.target ${DRO_TARGET}(knob dro=real|fake) 가 선택.
# 코드 변경은 `make deploy init [<knob> <value>...] && make up` 의 풀 rebuild 로만 반영.
FROM python:3.14-slim AS production

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

COPY shared/ /shared/

COPY 200.DRO/pyproject.toml 200.DRO/uv.lock* ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY 200.DRO/src/ src/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# 포트는 compose 가 $PORT env 로 주입 (topology.yaml → .env.topology 가 SoT).
# EXPOSE 는 documentation only — 실제 publishing 은 compose 의 ports: 가 결정.
CMD exec uv run uvicorn src.main:app --host 0.0.0.0 --port "${PORT}"


# ─────────────────────────────────────────────────────────────────────────────
# mock stage — dro:fake (via:image knob dro=fake → DRO_TARGET=mock → 이 타깃 빌드).
# minimal: fastapi/uvicorn/httpx/pyyaml 만. production 과 독립 (actor mock 패턴 동형).
# spawn 수신 → tests/data/dro-tapes(mount) 의 tape 를 /events SSE 로 재생 — mocks/dro_app.
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.14-slim AS mock

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

COPY 200.DRO/mocks/ ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev

CMD exec uv run uvicorn dro_app.app:app --host 0.0.0.0 --port "${PORT}"
