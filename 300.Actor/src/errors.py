"""Actor 의 단일 에러 envelope + FastAPI exception handler.

모든 non-2xx 응답은 다음 모양 (DRO·Nexus 와 동일 — venezia_contracts ErrorEnvelope):

    {"error": {"code": "<ErrorCode>", "message": "<str>", "details": {...optional}}}

HTTPException / 요청검증오류 / 미처리 예외를 자동으로 envelope 로 변환.
router 의 명시 에러(/tool 4xx·5xx, 503)는 `envelope()` 로 직접 본문을 구성한다.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from venezia_contracts.models.dro_api.error import ErrorBody, ErrorCode, ErrorEnvelope

log = logging.getLogger(__name__)


# HTTP status → ErrorCode 기본 매핑 (HTTPException 호환용).
_STATUS_TO_CODE: dict[int, ErrorCode] = {
    400: ErrorCode.validation_failed,
    404: ErrorCode.not_found,
    429: ErrorCode.rate_limited,
    503: ErrorCode.rate_limited,
}


def envelope(code: ErrorCode, message: str, details: dict[str, Any] | None = None) -> dict:
    return ErrorEnvelope(error=ErrorBody(code=code, message=message, details=details)).model_dump(
        mode="json", exclude_none=True
    )


async def _http_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    # FastAPI exception_handler 타입 narrowing
    assert isinstance(exc, HTTPException)  # nosec B101
    code = _STATUS_TO_CODE.get(exc.status_code, ErrorCode.internal)
    detail = exc.detail
    message = str(detail) if detail is not None else exc.__class__.__name__
    return JSONResponse(envelope(code, message), status_code=exc.status_code)


async def _validation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    # FastAPI exception_handler 타입 narrowing
    assert isinstance(exc, RequestValidationError)  # nosec B101
    return JSONResponse(
        envelope(
            ErrorCode.validation_failed,
            "request validation failed",
            {"fields": exc.errors()},
        ),
        status_code=422,
    )


async def _generic_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    log.exception("actor.unhandled_exception")
    return JSONResponse(
        envelope(ErrorCode.internal, str(exc) or exc.__class__.__name__),
        status_code=500,
    )


def install(app: FastAPI) -> None:
    """FastAPI app 에 exception handler 등록."""
    app.add_exception_handler(HTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(Exception, _generic_exception_handler)
