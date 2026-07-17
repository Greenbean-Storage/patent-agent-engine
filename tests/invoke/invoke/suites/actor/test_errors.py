"""300.Actor errors — envelope() + install() exception handlers (invoke 단위).

대상: 300.Actor/src/errors.py
  - envelope(code, message, details?) → {"error":{"code","message","details?}} (exclude_none).
  - install(app): HTTPException(status→code 매핑·else internal) / RequestValidationError(422
    validation_failed) / 미처리 Exception(500 internal) 를 ErrorEnvelope 로 변환.

전략: errors.install 한 fresh FastAPI app 에 각 에러를 유발하는 라우트를 달아 httpx
ASGITransport 로 호출, 응답 envelope 를 진짜 assert. 미처리 Exception 은
raise_app_exceptions=False 로 핸들러 응답을 받는다.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "300.Actor"))

from src import errors  # noqa: E402
from venezia_contracts.models.dro_api.error import ErrorCode  # noqa: E402


def test_envelope_shape_and_exclude_none():
    assert errors.envelope(ErrorCode.not_found, "nope") == {
        "error": {"code": "not_found", "message": "nope"}
    }
    with_details = errors.envelope(ErrorCode.validation_failed, "bad", {"field": "x"})
    assert with_details == {
        "error": {"code": "validation_failed", "message": "bad", "details": {"field": "x"}}
    }


class _Body(BaseModel):
    name: str


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/http-mapped")
    async def _mapped():
        raise HTTPException(404, "missing thing")

    @app.get("/http-unmapped")
    async def _unmapped():
        raise HTTPException(418, "teapot")

    @app.post("/validate")
    async def _validate(body: _Body):  # noqa: ARG001
        return {"ok": body.name}

    @app.get("/boom")
    async def _boom():
        raise ValueError("kaboom")

    errors.install(app)
    return app


def _client(app: FastAPI, *, raise_app: bool = True) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=raise_app),
        base_url="http://test",
    )


def test_http_exception_mapped_status_to_code():
    app = _app()

    async def _run():
        async with _client(app) as c:
            r = await c.get("/http-mapped")
            assert r.status_code == 404
            assert r.json() == {"error": {"code": "not_found", "message": "missing thing"}}

    asyncio.run(_run())


def test_http_exception_unmapped_status_internal():
    app = _app()

    async def _run():
        async with _client(app) as c:
            r = await c.get("/http-unmapped")
            assert r.status_code == 418
            body = r.json()
            assert body["error"]["code"] == "internal"
            assert body["error"]["message"] == "teapot"

    asyncio.run(_run())


def test_request_validation_error_envelope():
    app = _app()

    async def _run():
        async with _client(app) as c:
            r = await c.post("/validate", json={})  # name 누락
            assert r.status_code == 422
            body = r.json()
            assert body["error"]["code"] == "validation_failed"
            assert body["error"]["message"] == "request validation failed"
            assert "fields" in body["error"]["details"]

    asyncio.run(_run())


def test_generic_exception_envelope_500():
    app = _app()

    async def _run():
        async with _client(app, raise_app=False) as c:
            r = await c.get("/boom")
            assert r.status_code == 500
            body = r.json()
            assert body["error"]["code"] == "internal"
            assert body["error"]["message"] == "kaboom"

    asyncio.run(_run())
