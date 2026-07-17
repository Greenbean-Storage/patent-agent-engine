"""KIPRIS API wrapper tools — 외부 데이터 소스(KIPRIS Plus API) 호출 wrapper 만 도구.

실 파이프라인이 호출하는 도구는 단 2 종:
  - `kipris.search_patents`   (P03.R01.step1)
  - `kipris.get_patent_detail` (P03.R11.step1)

KIPRIS RAG 자체는 도구가 아니라 P03 의 chain dispatch graph (R00 → R01 → R02 → R11) 로 분해됨.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .. import register

log = logging.getLogger(__name__)


def _client():
    """KiprisClient lazy 생성 — config 로딩 순서 보호."""
    from .client import get_kipris_client

    return get_kipris_client()


@register("kipris.search_patents")
async def search_patents(
    queries: list[dict[str, Any]] | None = None,
    max_results_per_query: int | None = None,
    query: str | None = None,
    max_results: int | None = None,
) -> dict[str, Any]:
    """KIPRIS 검색 — P{NN} 포맷의 search step 용 (list 처리).

    동작:
    - queries (list of {query: str, type?: str, ...}) 받으면 각 query 에 KIPRIS 호출 후
      list 로 묶음.
    - 단일 query 받으면 단일 검색.
    - KIPRIS_MODE=fake (kipris knob) 면 canned 반환 — 실 API·키 불요 (fake.py, 3k).
    """
    from ... import engine_config
    from ...config import settings

    # 결과 수 기본값 = engine.config tools.kipris (fake 경로 포함 동일 의미론)
    kcfg = engine_config.tools()["kipris"]
    if max_results_per_query is None:
        max_results_per_query = int(kcfg["max_results_per_query"])
    if max_results is None:
        max_results = int(kcfg["max_results"])

    if settings.KIPRIS_MODE == "fake":
        from .fake import search_patents_fake  # lazy — config 로딩 순서 보호

        return await search_patents_fake(
            queries=queries,
            max_results_per_query=max_results_per_query,
            query=query,
            max_results=max_results,
        )
    if settings.KIPRIS_MODE != "real":
        raise RuntimeError(f"unknown KIPRIS_MODE: {settings.KIPRIS_MODE!r} (real|fake)")
    if not settings.KIPRIS_API_KEY:
        raise RuntimeError("KIPRIS_API_KEY not set — venezia_secrets 로딩 실패 가능성")

    async def _one(q_text: str, n: int) -> dict[str, Any]:
        if not q_text:
            return {"query": "", "patents": []}
        c = _client()
        results = await c.search_patents(q_text, max_results=n)
        return {"query": q_text, "patents": [r.to_dict() for r in results]}

    if queries:
        # 외부 API 동시 호출 cap — engine.config tools.kipris.max_concurrency 집행
        fan_out = asyncio.Semaphore(int(kcfg["max_concurrency"]))

        async def _wrap(q_item: dict[str, Any]) -> dict[str, Any]:
            q_text = q_item.get("query") if isinstance(q_item, dict) else str(q_item)
            async with fan_out:
                return await _one(q_text or "", max_results_per_query)

        results = await asyncio.gather(*[_wrap(q) for q in queries], return_exceptions=True)
        normalized: list[dict[str, Any]] = []
        for r in results:
            if isinstance(r, BaseException):
                normalized.append({"query": "", "patents": [], "error": str(r)})
            else:
                normalized.append(r)
        return {"results": normalized}

    if query:
        return await _one(query, max_results)
    return {"results": []}


@register("kipris.get_patent_detail")
async def get_patent_detail(application_number: str) -> dict[str, Any]:
    """KIPRIS 특허 상세 조회 — 키 누락 시 즉시 raise (silent stub 금지).

    KIPRIS_MODE=fake 면 canned 반환 (fake.py, 3k).
    """
    from ...config import settings

    if settings.KIPRIS_MODE == "fake":
        from .fake import get_patent_detail_fake  # lazy — config 로딩 순서 보호

        return await get_patent_detail_fake(application_number)
    if settings.KIPRIS_MODE != "real":
        raise RuntimeError(f"unknown KIPRIS_MODE: {settings.KIPRIS_MODE!r} (real|fake)")
    if not settings.KIPRIS_API_KEY:
        raise RuntimeError("KIPRIS_API_KEY not set")
    c = _client()
    detail = await c.get_patent_detail(application_number)
    return {
        "application_number": application_number,
        "detail": detail.to_dict() if detail else None,
    }
