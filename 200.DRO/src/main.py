"""200.DRO 앱 entrypoint — 순수 내부 체인 실행기 (sub-plan ② 코어 컷오버).

외부 클라이언트 표면 0 — 모든 client REST/WS 는 Nexus 게이트웨이가 소유. DRO 는 단일
ASGI app · 단일 포트(59200)에 control(`POST /control/spawn`) + event SSE
(`GET /events/{user_id}/{work_id}`) + `/health` 만 호스팅. 인증 없음(내부망 신뢰).
구 production/debug 이원화·:59290·auth·WS server·media·event_mapper 전부 제거.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from venezia_logging import get_logger, setup_logging

from . import errors, secrets, worker  # noqa: F401  — inject env vars before config is read
from .cm_client import get_cm_client
from .config import settings
from .router import router

setup_logging()
log = get_logger()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    log.info("dro.startup app=%s", _app.title)
    # 재시작 자동복구 (A-3) — 죽기 전 돌던 미완 chain 을 CM 에서 찾아 재개 (best-effort).
    try:
        await worker.resume_active_chains()
    except Exception:  # noqa: BLE001
        log.exception("dro.startup resume_active_chains failed")
    try:
        yield
    finally:
        # 전 worker cancel 후 CM client close (in-flight cm 호출이 닫힌 client 안 치게).
        await worker.shutdown_all()
        await get_cm_client().aclose()
        log.info("dro.shutdown app=%s", _app.title)


# ─── 내부 app (Nexus 게이트웨이 전용 — 외부 비노출) ──────────────────────────
app = FastAPI(
    title="DRO — Distributed Reasoning Orchestrator (internal executor)",
    version="2.0.0",
    lifespan=lifespan,
    openapi_url="/api/v1/openapi.json",
)
errors.install(app)
app.include_router(router)


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "service": "dro",
        "llm_mode": settings.LLM_MODE,
    }
