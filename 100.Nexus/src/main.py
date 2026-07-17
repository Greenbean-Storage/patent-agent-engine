"""100.Nexus 앱 entrypoint — mypage 영역 (auth + account + work CRUD/metadata).

DRO 의 chain runtime·WS·docx 생성 책임 제거된 가벼운 컨테이너.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from venezia_contracts.models.dro_api.account_api import HealthResponse
from venezia_logging import get_logger, setup_logging

from . import errors, secrets  # noqa: F401  — secrets 가 import 시점에 env 주입
from .cm_client import get_cm_client
from .config import settings
from .router import router

setup_logging()
log = get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # heartbeat = native WebSocket ping/pong (uvicorn keepalive) — app-level loop 없음.
    log.info("nexus.startup app=%s", app.title)
    try:
        yield
    finally:
        await get_cm_client().aclose()
        log.info("nexus.shutdown app=%s", app.title)


app = FastAPI(
    title="100.Nexus — mypage (auth + account + work CRUD/metadata)",
    version="1.0.0",
    lifespan=lifespan,
    openapi_url="/api/v1/openapi.json",
    # B7: 외부 base 선언 — 경로가 이미 /api/v1·/health 프리픽스를 포함하므로 host-only
    # (server url 에 /api/v1 넣으면 double-prefix). {host} 변수로 환경별 종단 치환.
    servers=[
        {
            "url": "https://{host}",
            "variables": {"host": {"default": "api.venezia.example"}},
        }
    ],
)
errors.install(app)
app.include_router(router)


# A-10: alias/meta 의 If-Match 는 **필수** + 무헤더 → 428. 핸들러가 428 raise 하려면 FastAPI
# param 은 optional(default=None)이라야 요청이 핸들러까지 도달하므로(required=True 면 FastAPI 가
# 422), 스펙(openapi)에서만 required·428 을 명시 — 동작(428)과 계약을 일치시킨다.
_IF_MATCH_REQUIRED = (
    ("/api/v1/user/account/alias", "put"),
    ("/api/v1/works/{work_id}/meta", "patch"),
)


def _custom_openapi() -> dict[str, Any]:
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title, version=app.version, routes=app.routes, servers=app.servers
    )
    err_ref = {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorEnvelope"}}}
    for path, method in _IF_MATCH_REQUIRED:
        op = schema.get("paths", {}).get(path, {}).get(method)
        if not op:
            continue
        for param in op.get("parameters", []):
            if param.get("name") == "If-Match":
                param["required"] = True
        op.setdefault("responses", {})["428"] = {
            "description": "If-Match 헤더 필수 (precondition required)",
            "content": err_ref,
        }
    app.openapi_schema = schema
    return schema


app.openapi = _custom_openapi  # type: ignore[method-assign]


@app.get("/health", response_model=HealthResponse)
async def health() -> dict[str, Any]:
    return {"status": "ok", "service": "nexus", "auth_mode": settings.AUTH_MODE.lower()}
