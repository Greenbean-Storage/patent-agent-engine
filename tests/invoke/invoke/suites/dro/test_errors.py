"""200.DRO errors — APIError + ErrorEnvelope + FastAPI exception handler 등록 (invoke 단위)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "200.DRO"))
sys.path.insert(0, str(ROOT / "shared"))

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from venezia_contracts.models.dro_api.error import ErrorCode  # noqa: E402

from src.errors import (  # noqa: E402
    APIError,
    _api_error_handler,
    _envelope,
    _generic_exception_handler,
    _http_exception_handler,
    _STATUS_TO_CODE,
    _validation_error_handler,
    install,
)

# --------------------------------------------------------------------------- #
# APIError                                                                     #
# --------------------------------------------------------------------------- #


def test_apierror_stores_all_fields():
    exc = APIError(ErrorCode.work_not_found, 404, "work X missing", {"work_id": "X"})
    assert exc.code is ErrorCode.work_not_found
    assert exc.status == 404
    assert exc.message == "work X missing"
    assert exc.details == {"work_id": "X"}
    # message 는 base Exception 으로도 전파
    assert str(exc) == "work X missing"


def test_apierror_details_default_none():
    exc = APIError(ErrorCode.conflict, 409, "dup")
    assert exc.details is None
    assert isinstance(exc, Exception)


# --------------------------------------------------------------------------- #
# _envelope — exclude_none 동작                                                #
# --------------------------------------------------------------------------- #


def test_envelope_with_details():
    env = _envelope(ErrorCode.validation_failed, "bad", {"field": "y"})
    assert env == {
        "error": {
            "code": "validation_failed",
            "message": "bad",
            "details": {"field": "y"},
        }
    }


def test_envelope_excludes_none_details():
    env = _envelope(ErrorCode.internal, "boom")
    assert env == {"error": {"code": "internal", "message": "boom"}}
    assert "details" not in env["error"]


# --------------------------------------------------------------------------- #
# 핸들러 직접 호출 (fake Request = None)                                        #
# --------------------------------------------------------------------------- #


def _call(handler, exc):
    return asyncio.run(handler(None, exc))


def test_api_error_handler_direct():
    resp = _call(_api_error_handler, APIError(ErrorCode.conflict, 409, "nope", {"why": "x"}))
    assert resp.status_code == 409
    assert resp.body == _to_bytes(
        {"error": {"code": "conflict", "message": "nope", "details": {"why": "x"}}}
    )


def test_http_exception_handler_str_detail():
    resp = _call(_http_exception_handler, HTTPException(status_code=404, detail="gone"))
    assert resp.status_code == 404
    assert resp.body == _to_bytes({"error": {"code": "not_found", "message": "gone"}})


def test_http_exception_handler_none_detail_uses_class_name():
    # detail=None → message 는 HTTPException 클래스명
    exc = HTTPException(status_code=409)
    exc.detail = None  # type: ignore[assignment]
    resp = _call(_http_exception_handler, exc)
    assert resp.status_code == 409
    assert resp.body == _to_bytes({"error": {"code": "conflict", "message": "HTTPException"}})


def test_http_exception_handler_unmapped_status_falls_to_internal():
    # 418 은 _STATUS_TO_CODE 에 없음 → ErrorCode.internal
    resp = _call(_http_exception_handler, HTTPException(status_code=418, detail="teapot"))
    assert resp.status_code == 418
    assert resp.body == _to_bytes({"error": {"code": "internal", "message": "teapot"}})


def test_http_exception_handler_dict_detail_with_message():
    detail = {"message": "custom msg", "work_id": "W1", "hint": "h"}
    resp = _call(_http_exception_handler, HTTPException(status_code=404, detail=detail))
    assert resp.status_code == 404
    assert resp.body == _to_bytes(
        {
            "error": {
                "code": "not_found",
                "message": "custom msg",
                "details": {"work_id": "W1", "hint": "h"},
            }
        }
    )


def test_http_exception_handler_dict_detail_with_detail_key():
    # message 키 없고 detail 키 → message 로 사용, details 는 detail 키 포함 (message 키만 제외)
    detail = {"detail": "via detail key", "extra": 1}
    resp = _call(_http_exception_handler, HTTPException(status_code=400, detail=detail))
    assert resp.status_code == 400
    assert resp.body == _to_bytes(
        {
            "error": {
                "code": "validation_failed",
                "message": "via detail key",
                "details": {"detail": "via detail key", "extra": 1},
            }
        }
    )


def test_http_exception_handler_dict_detail_no_message_uses_class_name():
    # message/detail 둘 다 없음 (falsy) → 클래스명. details 는 그대로.
    detail = {"foo": "bar"}
    resp = _call(_http_exception_handler, HTTPException(status_code=401, detail=detail))
    assert resp.status_code == 401
    assert resp.body == _to_bytes(
        {
            "error": {
                "code": "unauthorized",
                "message": "HTTPException",
                "details": {"foo": "bar"},
            }
        }
    )


def test_validation_error_handler_direct():
    errs = [{"loc": ("body", "x"), "msg": "field required", "type": "missing"}]
    resp = _call(_validation_error_handler, RequestValidationError(errs))
    assert resp.status_code == 422
    body = _from_bytes(resp.body)
    assert body["error"]["code"] == "validation_failed"
    assert body["error"]["message"] == "request validation failed"
    fields = body["error"]["details"]["fields"]
    assert fields[0]["msg"] == "field required"
    assert fields[0]["loc"] == ["body", "x"]


def test_generic_exception_handler_with_message():
    resp = _call(_generic_exception_handler, RuntimeError("kaboom"))
    assert resp.status_code == 500
    assert resp.body == _to_bytes({"error": {"code": "internal", "message": "kaboom"}})


def test_generic_exception_handler_empty_message_uses_class_name():
    # str(exc) 가 빈 문자열 → 클래스명 fallback
    resp = _call(_generic_exception_handler, ValueError(""))
    assert resp.status_code == 500
    assert resp.body == _to_bytes({"error": {"code": "internal", "message": "ValueError"}})


# --------------------------------------------------------------------------- #
# _STATUS_TO_CODE 매핑 전수                                                     #
# --------------------------------------------------------------------------- #


def test_status_to_code_mapping():
    assert _STATUS_TO_CODE == {
        400: ErrorCode.validation_failed,
        401: ErrorCode.unauthorized,
        404: ErrorCode.not_found,
        409: ErrorCode.conflict,
        501: ErrorCode.not_implemented,
    }


# --------------------------------------------------------------------------- #
# install — 실제 FastAPI app + httpx ASGITransport 통합                         #
# --------------------------------------------------------------------------- #


def _build_app() -> FastAPI:
    from pydantic import BaseModel

    app = FastAPI()
    install(app)

    class _Body(BaseModel):
        n: int

    @app.get("/api-error")
    async def _api_error():
        raise APIError(ErrorCode.work_not_found, 404, "no such work", {"work_id": "W9"})

    @app.get("/http-401")
    async def _http_401():
        raise HTTPException(status_code=401, detail="need token")

    @app.get("/http-409")
    async def _http_409():
        raise HTTPException(status_code=409, detail={"message": "dup", "key": "k1"})

    @app.get("/http-501")
    async def _http_501():
        raise HTTPException(status_code=501, detail="not yet")

    @app.get("/boom")
    async def _boom():
        raise RuntimeError("unexpected")

    @app.post("/validate")
    async def _validate(body: _Body):  # pragma: no cover - body never reached on 422
        return {"n": body.n}

    return app


def _run(coro):
    return asyncio.run(coro)


def test_install_registers_four_handlers():
    app = FastAPI()
    install(app)
    assert APIError in app.exception_handlers
    assert HTTPException in app.exception_handlers
    assert RequestValidationError in app.exception_handlers
    assert Exception in app.exception_handlers


def test_integration_api_error(asgi_client):
    app = _build_app()

    async def _go():
        async with asgi_client(app) as c:
            r = await c.get("/api-error")
            assert r.status_code == 404
            assert r.json() == {
                "error": {
                    "code": "work_not_found",
                    "message": "no such work",
                    "details": {"work_id": "W9"},
                }
            }

    _run(_go())


def test_integration_http_401(asgi_client):
    app = _build_app()

    async def _go():
        async with asgi_client(app) as c:
            r = await c.get("/http-401")
            assert r.status_code == 401
            assert r.json() == {"error": {"code": "unauthorized", "message": "need token"}}

    _run(_go())


def test_integration_http_409_dict_detail(asgi_client):
    app = _build_app()

    async def _go():
        async with asgi_client(app) as c:
            r = await c.get("/http-409")
            assert r.status_code == 409
            assert r.json() == {
                "error": {"code": "conflict", "message": "dup", "details": {"key": "k1"}}
            }

    _run(_go())


def test_integration_http_501(asgi_client):
    app = _build_app()

    async def _go():
        async with asgi_client(app) as c:
            r = await c.get("/http-501")
            assert r.status_code == 501
            assert r.json() == {"error": {"code": "not_implemented", "message": "not yet"}}

    _run(_go())


def test_integration_validation_422(asgi_client):
    app = _build_app()

    async def _go():
        async with asgi_client(app) as c:
            r = await c.post("/validate", json={"n": "not-an-int"})
            assert r.status_code == 422
            body = r.json()
            assert body["error"]["code"] == "validation_failed"
            assert body["error"]["message"] == "request validation failed"
            assert isinstance(body["error"]["details"]["fields"], list)
            assert body["error"]["details"]["fields"]

    _run(_go())


def test_integration_generic_500(asgi_client):
    app = _build_app()

    async def _go():
        # ASGITransport 가 핸들러 예외를 재던지지 않도록 raise_app_exceptions=False
        transport = _transport(app)
        import httpx

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.get("/boom")
            assert r.status_code == 500
            assert r.json() == {"error": {"code": "internal", "message": "unexpected"}}

    _run(_go())


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #


def _to_bytes(obj: dict) -> bytes:
    import json

    return json.dumps(obj, separators=(",", ":")).encode()


def _from_bytes(b: bytes) -> dict:
    import json

    return json.loads(b)


def _transport(app):
    import httpx

    return httpx.ASGITransport(app=app, raise_app_exceptions=False)
