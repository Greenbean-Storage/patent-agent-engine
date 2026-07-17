from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ErrorCode(str, Enum):
    unauthorized = "unauthorized"
    not_found = "not_found"
    validation_failed = "validation_failed"
    conflict = "conflict"
    precondition_required = "precondition_required"  # 428 — If-Match 필수(A-10)
    rate_limited = "rate_limited"
    internal = "internal"
    not_implemented = "not_implemented"  # 501 — placeholder endpoint (proposal / phase-transition)
    pipeline_ambiguous = "pipeline_ambiguous"  # debug app 전용
    pipeline_unknown = "pipeline_unknown"  # debug app 전용
    work_not_found = "work_not_found"
    document_not_ready = "document_not_ready"
    content_not_ready = "content_not_ready"


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ErrorCode
    message: str
    details: dict[str, Any] | None = None


class ErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ErrorBody = Field(..., description="에러 본문")
