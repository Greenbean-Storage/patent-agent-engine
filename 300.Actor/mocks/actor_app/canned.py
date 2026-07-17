"""canned tool 출력 — default 파이프라인(P01.R00·P02.R00·P03.R00·R01·R02)이 호출하는 6 tool (3c-1).

실 handler 와 동형 shape, CM write 만 생략 (3c-2 — mock 의 모델 CM-write 0; RT.output 은
DRO orchestrator 가 dispatch SSE result 로 PATCH). 그 외 tool = 미등록 → /tool 404.
미생성 fixture/tool 의 NEXT-PLAN 은 `tests/data/kipris-fixtures/README.md`.

kipris canned 데이터 = `{KIPRIS_FIXTURE_DIR}` (compose 가 `tests/data/kipris-fixtures` 를
ro mount — real-actor kipris:fake(`src/tools/kipris/fake.py`) 와 단일 소스 공유). 파일 부재 = fail-loud (500).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

# 실 maturity.compute (deterministic 가중 합산) 를 P02.R00 fixture 2/3/4 입력에 적용한 정적 값.
# fixture 의 sub-score 가 바뀌면 이 값도 갱신 — verify 가 수치를 assert 하진 않음 (inert).
_MATURITY: dict[str, Any] = {
    "overall_score": 0.53,
    "scores": {
        "clarity": 0.62,
        "completeness": 0.42,
        "potential": 0.6,
    },
    "sub_scores": {
        "clarity": {"purpose": 0.65, "components": 0.6},
        "completeness": {"sequence": 0.5, "causality": 0.5, "embodiment": 0.3},
        "potential": {"differentiation": 0.65, "effect": 0.55},
    },
    "weights": {
        "clarity": 0.30,
        "completeness": 0.45,
        "potential": 0.25,
    },
    "sub_weights": {
        "clarity": {"purpose": 0.4, "components": 0.6},
        "completeness": {"sequence": 0.3, "causality": 0.3, "embodiment": 0.4},
        "potential": {"differentiation": 0.5, "effect": 0.5},
    },
}


def _kipris_data(name: str) -> Any:
    from . import config

    path = Path(config.KIPRIS_FIXTURE_DIR) / name
    return json.loads(path.read_text(encoding="utf-8"))  # 부재/parse 실패 = fail-loud → 500


async def _staging_save(**params: Any) -> dict[str, Any]:
    """실 staging.save 반환 동형 — CDS PUT 은 생략."""
    return {"ok": True}


async def _maturity_compute(**params: Any) -> dict[str, Any]:
    """실 maturity.compute 반환 동형 — 수치 정적, rationale 은 params 통과, CMM PUT 생략.

    model.maturity 는 Nexus 가 chain 완료(persona=2) 시 CM 에서 CMM fetch 로 생성 (DRO 미발사, #12).
    """
    rationales = {
        key: str((params.get(key) or {}).get("rationale", ""))
        for key in ("clarity", "completeness", "potential")
    }
    return {**_MATURITY, "rationales": rationales}


async def _roadmap_persist(**params: Any) -> dict[str, Any]:
    """실 roadmap.persist 반환 동형 — UR PUT 생략.

    model.roadmap 은 Nexus 가 chain 완료(persona=2) 시 CM 에서 UR fetch 로 생성 (DRO 미발사, #12).
    """
    items = params.get("items") or []
    return {"ok": True, "count": len(items) if isinstance(items, list) else 0}


async def _cm_append_conversation(**params: Any) -> dict[str, Any]:
    """실 cm.append_conversation 검증 동형 (role/content) — conversation append 는 생략."""
    message = params.get("message")
    if not isinstance(message, dict):
        raise ValueError(f"message must be a dict, got {type(message).__name__}")
    role = message.get("role")
    content = message.get("content")
    if role not in ("user", "assistant"):
        raise ValueError(f"message.role must be user|assistant, got {role!r}")
    if not isinstance(content, str):
        raise ValueError("message.content must be a string")
    return {"appended": True, "role": role, "content_chars": len(content)}


async def _kipris_search_patents(**params: Any) -> dict[str, Any]:
    """실 kipris.search_patents 반환 동형 — 전 query 가 동일 canned pool 을 받는다."""
    pool: list[dict[str, Any]] = _kipris_data("search_pool.json")
    queries = params.get("queries")
    if queries:
        n = int(params.get("max_results_per_query", 10))
        results = []
        for q_item in queries:
            q_text = q_item.get("query") if isinstance(q_item, dict) else str(q_item)
            results.append({"query": q_text or "", "patents": pool[:n]})
        return {"results": results}
    query = params.get("query")
    if query:
        n = int(params.get("max_results", 30))
        return {"query": str(query), "patents": pool[:n]}
    return {"results": []}


async def _kipris_get_patent_detail(**params: Any) -> dict[str, Any]:
    """실 kipris.get_patent_detail 반환 동형 — details.json map lookup."""
    details: dict[str, Any] = _kipris_data("details.json")
    application_number = str(params.get("application_number") or "")
    return {
        "application_number": application_number,
        "detail": details.get(application_number),
    }


CANNED: dict[str, Callable[..., Awaitable[dict[str, Any]]]] = {
    "staging.save": _staging_save,
    "maturity.compute": _maturity_compute,
    "roadmap.persist": _roadmap_persist,
    "cm.append_conversation": _cm_append_conversation,
    "kipris.search_patents": _kipris_search_patents,
    "kipris.get_patent_detail": _kipris_get_patent_detail,
}
