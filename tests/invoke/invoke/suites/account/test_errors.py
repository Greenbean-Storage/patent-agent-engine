"""100.Nexus errors envelope + FastAPI exception handler — invoke 단위테스트 (≥99% line).

대상: 100.Nexus/src/errors.py. 작은 FastAPI app 에 errors.install(app) 후
의도적으로 각 예외를 raise 하는 라우트를 추가하고 httpx.ASGITransport 로 호출,
envelope 모양 {"error":{"code","message","details?}} + status 를 검증.

커버:
  - _api_error_handler         : APIError(code/status/message/details) — details 有/無
  - _http_exception_handler    : _STATUS_TO_CODE 매핑 status + 미매핑 status→internal;
                                 detail=dict(message 키 有 / 無→detail / 둘다 falsy→__class__.__name__)
                                 + str detail + detail None→__class__.__name__
  - _validation_error_handler  : 422 + fields
  - _generic_exception_handler : 500 (일반 메시지 — 예외 문자열 미노출)
  - install                    : 4 handler 등록
  - APIError 클래스 생성자 직접 검증

async 테스트는 기존 suite 패턴대로 동기 def 안에서 asyncio.run(...) 로 호출.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "100.Nexus"))

import httpx  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from src import errors  # noqa: E402
from src.errors import APIError, install  # noqa: E402
from venezia_contracts.models.dro_api.error import ErrorCode  # noqa: E402


# ── app 조립 ─────────────────────────────────────────────────────────────────


class _Body(BaseModel):
    name: str


def _build_app() -> FastAPI:
    """각 예외 경로를 의도적으로 raise 하는 라우트 모음 + errors.install."""
    app = FastAPI()
    install(app)

    @app.get("/api-error-details")
    async def _api_error_details():
        raise APIError(ErrorCode.work_not_found, 404, "work X not found", {"work_id": "X"})

    @app.get("/api-error-nodetails")
    async def _api_error_nodetails():
        raise APIError(ErrorCode.conflict, 409, "nope")

    @app.get("/http-mapped")
    async def _http_mapped():
        # 404 → _STATUS_TO_CODE → not_found, str detail
        raise HTTPException(status_code=404, detail="thing gone")

    @app.get("/http-unmapped")
    async def _http_unmapped():
        # 418 미매핑 → ErrorCode.internal, str detail
        raise HTTPException(status_code=418, detail="teapot")

    @app.get("/http-dict-message")
    async def _http_dict_message():
        # detail=dict, message 키 有 → message 사용, 나머지 키는 details
        raise HTTPException(
            status_code=409,
            detail={"message": "conflict here", "field": "alias", "extra": 1},
        )

    @app.get("/http-dict-detailkey")
    async def _http_dict_detailkey():
        # detail=dict, message 키 無·detail 키 有 → detail 값을 message 로
        raise HTTPException(status_code=400, detail={"detail": "fallback msg", "x": 2})

    @app.get("/http-dict-empty")
    async def _http_dict_empty():
        # detail=dict, message/detail 둘다 falsy → message = exc.__class__.__name__
        raise HTTPException(status_code=400, detail={"message": "", "other": "y"})

    @app.get("/http-none")
    async def _http_none():
        # detail None → message = exc.__class__.__name__.
        # Starlette HTTPException 은 detail=None 을 status phrase 로 채우므로
        # 생성 후 .detail 을 직접 None 으로 비워 핸들러의 None 분기를 친다.
        exc = HTTPException(status_code=401)
        exc.detail = None
        raise exc

    @app.post("/validation")
    async def _validation(body: _Body):
        return {"ok": body.name}

    @app.get("/generic")
    async def _generic():
        raise RuntimeError("boom")

    @app.get("/generic-empty")
    async def _generic_empty():
        # 빈 예외도 일반 메시지로 (외부 노출 방지)
        raise RuntimeError("")

    return app


def _get(path: str, **kw):
    """ASGITransport 로 app 호출. 서버 예외를 envelope 로 받기 위해 raise_app_exceptions=False."""
    app = _build_app()

    async def _run():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            method = kw.pop("method", "GET")
            return await client.request(method, path, **kw)

    return asyncio.run(_run())


# ── APIError 핸들러 ──────────────────────────────────────────────────────────


def test_api_error_with_details():
    resp = _get("/api-error-details")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "work_not_found"
    assert body["error"]["message"] == "work X not found"
    assert body["error"]["details"] == {"work_id": "X"}


def test_api_error_without_details():
    resp = _get("/api-error-nodetails")
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"]["code"] == "conflict"
    assert body["error"]["message"] == "nope"
    # details=None → exclude_none → 키 자체가 없어야 함
    assert "details" not in body["error"]


# ── HTTPException 핸들러 ──────────────────────────────────────────────────────


def test_http_mapped_status_str_detail():
    resp = _get("/http-mapped")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["message"] == "thing gone"
    assert "details" not in body["error"]


def test_http_unmapped_status_internal():
    resp = _get("/http-unmapped")
    assert resp.status_code == 418
    body = resp.json()
    assert body["error"]["code"] == "internal"
    assert body["error"]["message"] == "teapot"


def test_http_dict_detail_with_message_key():
    resp = _get("/http-dict-message")
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"]["code"] == "conflict"
    assert body["error"]["message"] == "conflict here"
    # message 키 제외한 나머지가 details 로
    assert body["error"]["details"] == {"field": "alias", "extra": 1}


def test_http_dict_detail_with_detail_key():
    resp = _get("/http-dict-detailkey")
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "validation_failed"
    assert body["error"]["message"] == "fallback msg"
    # message 키가 없으므로 detail/x 모두 details 로
    assert body["error"]["details"] == {"detail": "fallback msg", "x": 2}


def test_http_dict_detail_empty_message_falls_back_to_classname():
    resp = _get("/http-dict-empty")
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "validation_failed"
    # message/detail 모두 falsy → exc.__class__.__name__
    assert body["error"]["message"] == "HTTPException"
    assert body["error"]["details"] == {"other": "y"}


def test_http_none_detail_falls_back_to_classname():
    resp = _get("/http-none")
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == "unauthorized"
    assert body["error"]["message"] == "HTTPException"
    assert "details" not in body["error"]


# ── RequestValidationError 핸들러 ─────────────────────────────────────────────


def test_validation_error():
    # 필수 필드 name 누락 → RequestValidationError
    resp = _get("/validation", method="POST", json={})
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "validation_failed"
    assert body["error"]["message"] == "request validation failed"
    fields = body["error"]["details"]["fields"]
    assert isinstance(fields, list)
    assert any(f.get("loc") for f in fields)


# ── generic Exception 핸들러 ─────────────────────────────────────────────────


def test_generic_exception():
    resp = _get("/generic")
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["code"] == "internal"
    # 외부 노출 방지 — 미처리 예외 문자열 대신 일반 메시지 (full trace 는 로그)
    assert body["error"]["message"] == "internal server error"


def test_generic_exception_empty():
    resp = _get("/generic-empty")
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["code"] == "internal"
    # 예외 내용과 무관하게 일반 메시지
    assert body["error"]["message"] == "internal server error"


# ── APIError 클래스 생성자 직접 ───────────────────────────────────────────────


def test_apierror_constructor_attributes():
    exc = APIError(ErrorCode.conflict, 409, "dup", {"k": "v"})
    assert exc.code == ErrorCode.conflict
    assert exc.status == 409
    assert exc.message == "dup"
    assert exc.details == {"k": "v"}
    # super().__init__(message) → str(exc) == message
    assert str(exc) == "dup"


def test_apierror_constructor_default_details_none():
    exc = APIError(ErrorCode.not_found, 404, "missing")
    assert exc.details is None


# ── install 등록 검증 ─────────────────────────────────────────────────────────


def test_install_registers_four_handlers():
    app = FastAPI()
    install(app)
    handlers = app.exception_handlers
    assert handlers.get(APIError) is errors._api_error_handler
    assert handlers.get(HTTPException) is errors._http_exception_handler
    assert handlers.get(RequestValidationError) is errors._validation_error_handler
    assert handlers.get(Exception) is errors._generic_exception_handler
