# 멀티스테이지: production(실 Actor) + mock(actor:fake — via:image ACTOR_TARGET=mock). hot reload 폐기.
# 코드 변경은 `make deploy init [<knob> <value>...] && make up` 의 풀 rebuild 로만 반영.
FROM python:3.14-slim AS production

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Drawing render CLIs (plantuml/openscad). schemdraw is a Python dep in pyproject.
RUN apt-get update && apt-get install -y --no-install-recommends \
        plantuml \
        openscad \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

COPY shared/ /shared/

COPY 300.Actor/pyproject.toml 300.Actor/uv.lock* ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY 300.Actor/src/ src/

# engine.config — persona 정의 + LLM/tool 운영 SoT (빌드타임 bake, 변경 반영 = make up 풀 rebuild)
COPY @deployment/engine.config.yaml /app/engine.config.yaml

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# 포트는 compose 가 $PORT env 로 주입 (topology.yaml → .env.topology 가 SoT —
# build-time 포트 고정 없음. unified 단일 actor :59300).
CMD exec uv run uvicorn src.main:app --host 0.0.0.0 --port "${PORT}"


# ─────────────────────────────────────────────────────────────────────────────
# mock stage — actor:fake (via:image knob actor=fake → ACTOR_TARGET=mock → 이 타깃 빌드).
# minimal: fastapi/uvicorn/httpx/pyyaml 만 (plantuml/openscad/fonts 없음). production 과 독립.
# /dispatch(SSE fixture replay) · /tool(canned) · busy-503 marker — mocks/actor_app.
# busy_markers/ 는 아래 COPY 로 이미지에 bake — marker 변경 = make up 풀 rebuild.
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.14-slim AS mock

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

COPY 300.Actor/mocks/ ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev

# 포트는 compose 가 $PORT env 로 주입 (real actor 와 동일).
CMD exec uv run uvicorn actor_app.app:app --host 0.0.0.0 --port "${PORT}"
