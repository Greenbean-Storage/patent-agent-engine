"""kipris:fake — canned 응답 (kipris knob via:config, 3k).

`settings.KIPRIS_FIXTURE_DIR`(`tests/data/kipris-fixtures` ro mount) 의 canned JSON 을
반환 — **mock-actor `mocks/actor_app/canned.py` 와 단일 소스·동일 의미론** (drift 0):
  - search: 모든 query 가 `search_pool.json` 배열의 [:max_results_per_query]
    (단일 query 는 [:max_results]). 빈 query 텍스트도 pool 반환 — real `_one` 은 빈
    query 에 빈 patents 를 주지만, fake 는 canned(mock) 쪽을 미러 (의도된 차이).
  - detail: `details.json`(app_no → PatentDetail.to_dict 동형 map) lookup, 없으면 None.

실 KIPRIS API·`.client`·`.cache` 미접촉 (import 하지 않음). KIPRIS_API_KEY 불요.
canned 파일 부재/parse 실패 = fail-loud raise.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def _data(name: str) -> Any:
    from ...config import settings

    path = Path(settings.KIPRIS_FIXTURE_DIR) / name
    return json.loads(path.read_text(encoding="utf-8"))  # 부재/parse 실패 = fail-loud


async def search_patents_fake(
    queries: list[dict[str, Any]] | None = None,
    max_results_per_query: int = 10,
    query: str | None = None,
    max_results: int = 30,
) -> dict[str, Any]:
    """실 search_patents 반환 동형 — canned pool 사용."""
    log.info("kipris fake — canned search (queries=%d)", len(queries or []))
    pool: list[dict[str, Any]] = _data("search_pool.json")
    if queries:
        results = []
        for q_item in queries:
            q_text = q_item.get("query") if isinstance(q_item, dict) else str(q_item)
            results.append({"query": q_text or "", "patents": pool[: int(max_results_per_query)]})
        return {"results": results}
    if query:
        return {"query": str(query), "patents": pool[: int(max_results)]}
    return {"results": []}


async def get_patent_detail_fake(application_number: str) -> dict[str, Any]:
    """실 get_patent_detail 반환 동형 — canned map lookup."""
    log.info("kipris fake — canned detail (%s)", application_number)
    details: dict[str, Any] = _data("details.json")
    return {
        "application_number": application_number,
        "detail": details.get(str(application_number)),
    }
