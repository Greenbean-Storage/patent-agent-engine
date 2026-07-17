"""maturity.compute — 7 sub-score 가중 합산 + CMM PUT.

DRO tool step (KIPRIS 패턴) — DRO 가 LLM 없이 `POST {actor_url}/tool/maturity.compute` 직접 호출.
LLM 비결정성 회피 위해 *정확한* 계산 (deterministic).

흐름:
  3 LLM step (clarity / completeness / potential) 의 sub-score dict 받음
  → 지표 score = sum(sub × sub_weights)
  → overall = sum(score × weights)
  → round(value, 2)
  → CMM PUT (단일 파일 overwrite, S3 versioning 이 history)
  → return payload (CMM 영속만 — WS model.maturity 는 Nexus 가 chain 완료 시 CM fetch, #12)

지표 키 = 짧은 이름 (A-2 전면 통일, 내부+외부 동일). 긴 의미 보존:
  clarity = 개념 명료성(concept clarity) · completeness = 명세 완성도(description completeness)
  · potential = 특허성 잠재력(patentability potential).

가중치 (master-milestone §39 + plan const):
  WEIGHTS = clarity 0.30 + completeness 0.45 + potential 0.25 (합 1.0)
  SUB_WEIGHTS:
    clarity = purpose 0.4 + components 0.6
    completeness = sequence 0.3 + causality 0.3 + embodiment 0.4
    potential = differentiation 0.5 + effect 0.5

invariant (invoke test 로 검증):
  - WEIGHTS 합 = 1.0
  - 각 SUB_WEIGHTS dict 합 = 1.0
  - 모든 sub-score / score / overall ∈ [0.0, 1.0]
  - 코드 const = schema const (drift 없음)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from ...cm_client import CMClient
from .. import register

log = logging.getLogger(__name__)


WEIGHTS: dict[str, float] = {
    "clarity": 0.30,
    "completeness": 0.45,
    "potential": 0.25,
}

SUB_WEIGHTS: dict[str, dict[str, float]] = {
    "clarity": {
        "purpose": 0.4,
        "components": 0.6,
    },
    "completeness": {
        "sequence": 0.3,
        "causality": 0.3,
        "embodiment": 0.4,
    },
    "potential": {
        "differentiation": 0.5,
        "effect": 0.5,
    },
}


def _client() -> CMClient:
    from ...config import settings

    return CMClient(settings.CM_URL)


def _validate_score(name: str, value: float) -> float:
    v = float(value)
    if not (0.0 <= v <= 1.0):
        raise ValueError(f"{name} out of range [0,1]: {v}")
    return v


@register("maturity.compute")
async def compute(
    clarity: dict[str, Any] | None = None,
    completeness: dict[str, Any] | None = None,
    potential: dict[str, Any] | None = None,
    user_id: str | None = None,
    work_id: str | None = None,
) -> dict[str, Any]:
    """3 LLM sub-score dict 받아 가중 합산 (지표 키 = 짧은 이름, A-2).

    params 형식 (pipeline placeholder 결과):
      clarity = {"purpose": float, "components": float, "rationale": str}
      completeness = {"sequence": float, "causality": float, "embodiment": float, "rationale": str}
      potential = {"differentiation": float, "effect": float, "rationale": str}
    """
    if not user_id or not work_id:
        raise ValueError(
            "user_id/work_id missing — DRO 가 자동 주입해야 함. "
            "tool category 가 'maturity.*' 인지 확인."
        )
    if not (clarity and completeness and potential):
        raise ValueError("all 3 sub-score dicts required (clarity/completeness/potential)")

    sub_scores: dict[str, dict[str, float]] = {
        "clarity": {
            "purpose": _validate_score("clarity.purpose", clarity["purpose"]),
            "components": _validate_score("clarity.components", clarity["components"]),
        },
        "completeness": {
            "sequence": _validate_score("completeness.sequence", completeness["sequence"]),
            "causality": _validate_score("completeness.causality", completeness["causality"]),
            "embodiment": _validate_score("completeness.embodiment", completeness["embodiment"]),
        },
        "potential": {
            "differentiation": _validate_score(
                "potential.differentiation", potential["differentiation"]
            ),
            "effect": _validate_score("potential.effect", potential["effect"]),
        },
    }

    scores: dict[str, float] = {}
    for indicator, subs in sub_scores.items():
        score = sum(subs[k] * SUB_WEIGHTS[indicator][k] for k in subs)
        scores[indicator] = round(score, 2)

    overall = round(sum(scores[i] * WEIGHTS[i] for i in WEIGHTS), 2)

    rationales = {
        "clarity": str(clarity.get("rationale", "")),
        "completeness": str(completeness.get("rationale", "")),
        "potential": str(potential.get("rationale", "")),
    }

    payload: dict[str, Any] = {
        "overall_score": overall,
        "scores": scores,
        "sub_scores": sub_scores,
        "weights": WEIGHTS,
        "sub_weights": SUB_WEIGHTS,
        "rationales": rationales,
        "last_updated": datetime.now(UTC).isoformat(),
    }

    cm = _client()
    try:
        await cm.put_concept_maturity_model(user_id, work_id, payload)
    finally:
        await cm.aclose()

    log.info(
        "maturity.compute uid=%s inv=%s overall=%.2f c=%.2f d=%.2f p=%.2f",
        user_id[:8],
        work_id[:8],
        overall,
        scores["clarity"],
        scores["completeness"],
        scores["potential"],
    )

    return {
        "overall_score": overall,
        "scores": scores,
        "sub_scores": sub_scores,
        "weights": WEIGHTS,
        "sub_weights": SUB_WEIGHTS,
        "rationales": rationales,
    }
