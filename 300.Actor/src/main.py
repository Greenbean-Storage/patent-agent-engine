from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import (
    errors,
    secrets,  # noqa: F401 — inject env vars before config is read
)
from .cm_client import get_cm_client
from .config import settings
from .router import router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await get_cm_client().aclose()


app = FastAPI(
    title=f"DRC Actor [{settings.ACTOR_ID}]",
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(router)
errors.install(app)


@app.get("/health")
async def health() -> dict:
    from . import engine_config, slots, tools

    return {
        "status": "ok",
        "actor_id": settings.ACTOR_ID,
        # 수락 집합 = engine.config personas (구 ACTOR_PERSONAS env 폐기 — unified)
        "personas": engine_config.persona_ids(),
        "tools": tools.list_available(),
        "llm_mode": settings.LLM_MODE,
        # 동시성 관측 — persona/tool 풀의 cap·inflight (slots.py, engine.config cap 집행)
        "slots": slots.snapshot(),
    }
