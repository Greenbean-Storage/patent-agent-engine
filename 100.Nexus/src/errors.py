"""Nexus 의 단일 에러 envelope + FastAPI exception handler.

모든 non-2xx 응답은 다음 모양:

    {"error": {"code": "<ErrorCode>", "message": "<str>", "details": {...optional}}}

기존 router 의 HTTPException(...) 호출들도 자동으로 envelope 로 변환됨 (http_exception_handler).
새 코드는 APIError 를 직접 raise 해서 code/details 를 명시할 수 있다.
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
    401: ErrorCode.unauthorized,
    404: ErrorCode.not_found,
    409: ErrorCode.conflict,
    428: ErrorCode.precondition_required,
    501: ErrorCode.not_implemented,
}


class APIError(Exception):
    """code/status/message/details 를 명시한 도메인 에러.

    `raise APIError(ErrorCode.work_not_found, 404, "work X not found")` 식.
    """

    def __init__(
        self,
        code: ErrorCode,
        status: int,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.message = message
        self.details = details


def _envelope(code: ErrorCode, message: str, details: dict[str, Any] | None = None) -> dict:
    return ErrorEnvelope(error=ErrorBody(code=code, message=message, details=details)).model_dump(
        mode="json", exclude_none=True
    )


async def _api_error_handler(_: Request, exc: Exception) -> JSONResponse:
    # FastAPI exception_handler 타입 narrowing
    assert isinstance(exc, APIError)  # nosec B101
    return JSONResponse(_envelope(exc.code, exc.message, exc.details), status_code=exc.status)


async def _http_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    # FastAPI exception_handler 타입 narrowing
    assert isinstance(exc, HTTPException)  # nosec B101
    code = _STATUS_TO_CODE.get(exc.status_code, ErrorCode.internal)
    detail = exc.detail
    if isinstance(detail, dict):
        message = str(detail.get("message") or detail.get("detail") or "")
        details = {k: v for k, v in detail.items() if k != "message"}
        if not message:
            message = exc.__class__.__name__
    else:
        message = str(detail) if detail is not None else exc.__class__.__name__
        details = None
    return JSONResponse(_envelope(code, message, details), status_code=exc.status_code)


async def _validation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    # FastAPI exception_handler 타입 narrowing
    assert isinstance(exc, RequestValidationError)  # nosec B101
    return JSONResponse(
        _envelope(
            ErrorCode.validation_failed,
            "request validation failed",
            {"fields": exc.errors()},
        ),
        status_code=422,
    )


async def _generic_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    # 외부 게이트웨이 — 미처리 예외 문자열을 client 에 노출하지 않는다 (full trace 는 로그).
    log.exception("nexus.unhandled_exception")
    return JSONResponse(
        _envelope(ErrorCode.internal, "internal server error"),
        status_code=500,
    )


def install(app: FastAPI) -> None:
    """FastAPI app 에 exception handler 등록."""
    app.add_exception_handler(APIError, _api_error_handler)
    app.add_exception_handler(HTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(Exception, _generic_exception_handler)
