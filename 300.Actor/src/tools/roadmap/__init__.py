"""roadmap.persist — user-roadmap.json (= top-level array) CM PUT.

DRO tool step — DRO 가 LLM 없이 `POST {actor_url}/tool/roadmap.persist` 직접 호출.
LLM (step 6 update_roadmap) 의 array output 을 받아 CM 에 단일 파일 overwrite.

흐름:
  1. items (= list of 8-field dicts) 받음
  2. 형식 검증 (필수 필드 + status enum + answer 정합성)
  3. CM PUT (top-level array)
  4. return {ok: True, count: len(items)}

D 안 자연 누적의 *영속화* 단계 — LLM 이 만든 list 를 그대로 저장.
같은 id 보존은 *LLM 책임* (instruction md 강조). tool 은 검증만.

user_id / work_id 는 DRO 의 _exec_tool_call 이 자동 주입.
"""

from __future__ import annotations

import logging
from typing import Any

from ...cm_client import CMClient
from .. import register

log = logging.getLogger(__name__)


_REQUIRED_FIELDS = frozenset(
    {"id", "title", "description", "status", "priority", "input_type", "options", "answer"}
)
_STATUS_VALUES = frozenset({"pending", "satisfied", "skipped"})
_INPUT_TYPES = frozenset({"chat", "selection", "checkbox", "keyword", "none"})


def _client() -> CMClient:
    from ...config import settings

    return CMClient(settings.CM_URL)


def _validate_item(item: Any, idx: int) -> None:
    if not isinstance(item, dict):
        raise ValueError(f"items[{idx}] must be a dict, got {type(item).__name__}")
    missing = _REQUIRED_FIELDS - set(item.keys())
    if missing:
        raise ValueError(f"items[{idx}] missing fields: {sorted(missing)}")
    extra = set(item.keys()) - _REQUIRED_FIELDS
    if extra:
        raise ValueError(f"items[{idx}] unknown fields: {sorted(extra)}")
    if item["status"] not in _STATUS_VALUES:
        raise ValueError(f"items[{idx}].status invalid: {item['status']!r}")
    if item["input_type"] not in _INPUT_TYPES:
        raise ValueError(f"items[{idx}].input_type invalid: {item['input_type']!r}")
    if item["status"] == "satisfied" and item["answer"] is None:
        raise ValueError(f"items[{idx}].status=satisfied but answer is null")
    if item["status"] in ("pending", "skipped") and item["answer"] is not None:
        raise ValueError(f"items[{idx}].status={item['status']} but answer is not null")


@register("roadmap.persist")
async def persist(
    items: list[dict[str, Any]] | None = None,
    user_id: str | None = None,
    work_id: str | None = None,
) -> dict[str, Any]:
    """Roadmap items list 받아 CM PUT.

    params 형식 (pipeline placeholder 결과):
      items = step 6 의 LLM output (top-level array)
    """
    if not user_id or not work_id:
        raise ValueError(
            "user_id/work_id missing — DRO 가 자동 주입해야 함. "
            "tool category 가 'roadmap.*' 인지 확인."
        )
    if items is None:
        raise ValueError("items required (top-level array)")
    if not isinstance(items, list):
        raise ValueError(f"items must be a list, got {type(items).__name__}")

    for idx, item in enumerate(items):
        _validate_item(item, idx)

    seen_ids: set[str] = set()
    for idx, item in enumerate(items):
        item_id = item["id"]
        if item_id in seen_ids:
            raise ValueError(f"items[{idx}].id duplicate: {item_id!r}")
        seen_ids.add(item_id)

    cm = _client()
    try:
        await cm.put_user_roadmap(user_id, work_id, items)
    finally:
        await cm.aclose()

    log.info(
        "roadmap.persist uid=%s inv=%s count=%d pending=%d satisfied=%d",
        user_id[:8],
        work_id[:8],
        len(items),
        sum(1 for i in items if i["status"] == "pending"),
        sum(1 for i in items if i["status"] == "satisfied"),
    )

    return {"ok": True, "count": len(items)}
