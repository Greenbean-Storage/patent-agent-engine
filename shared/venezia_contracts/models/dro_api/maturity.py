"""구체화 완성도 모델(CMM) 의 외부 응답.

WS `model.maturity.data` (구 maturity.updated, #12) 와 REST `estimate/maturity` 응답이
같은 shape 을 공유한다. baseline 4 수치 (overall_score + 3 sub) + 추가 필드 가능.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class MaturityScores(BaseModel):
    """3 sub-score + 향후 추가 sub-fields 가 들어올 자리 (additionalProperties).

    지표 키 = 짧은 이름 (A-2 전면 통일 — 내부 저장도 짧은 키라 alias 불요).
    의미: clarity=개념 명료성 · completeness=명세 완성도 · potential=특허성 잠재력.
    """

    model_config = ConfigDict(extra="allow")

    clarity: float = Field(..., ge=0.0, le=1.0)
    completeness: float = Field(..., ge=0.0, le=1.0)
    potential: float = Field(..., ge=0.0, le=1.0)


class MaturityResponse(BaseModel):
    """estimate/maturity 응답 + WS model.maturity payload (구 maturity.updated, #12).

    fresh invention (아직 평가 안 됨) 은 endpoint 가 200 + null 또는 404 — Step 3 에서
    결정. Pydantic 측은 Optional 처리.
    """

    model_config = ConfigDict(extra="allow")  # weights / rationales / 향후 필드

    overall_score: float = Field(..., ge=0.0, le=1.0)
    scores: MaturityScores
    weights: dict[str, float] | None = None
