"""staging.save — 구체화 단계 정보 stack (concept-discovery-stack.json) 영속.

DRO tool step (KIPRIS 패턴) — DRO 가 LLM 없이 `POST {actor_url}/tool/staging.save` 직접 호출.
LLM 의 step 0 (extract_to_stack) 이 만든 7 정보 필드를 받아 CM 에 PUT.
계산 없음, last_updated 추가 후 단일 파일 overwrite.

user_id / work_id 는 DRO 의 _exec_tool_call 이 자동 주입.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from ...cm_client import CMClient
from .. import register

log = logging.getLogger(__name__)


def _client() -> CMClient:
    from ...config import settings

    return CMClient(settings.CM_URL)


@register("staging.save")
async def save(
    purpose: str = "",
    components: list[str] | None = None,
    operation_sequence: list[str] | None = None,
    causality: list[str] | None = None,
    embodiments: list[str] | None = None,
    differentiation: str = "",
    effects: list[str] | None = None,
    user_id: str | None = None,
    work_id: str | None = None,
) -> dict[str, Any]:
    """ConceptDiscoveryStack 의 7 필드 받아 CM PUT.

    last_updated 는 여기서 추가 (LLM output 에 없음).
    """
    if not user_id or not work_id:
        raise ValueError(
            "user_id/work_id missing — DRO 가 자동 주입해야 함. "
            "tool category 가 'staging.*' 인지 확인."
        )

    payload: dict[str, Any] = {
        "purpose": purpose,
        "components": list(components or []),
        "operation_sequence": list(operation_sequence or []),
        "causality": list(causality or []),
        "embodiments": list(embodiments or []),
        "differentiation": differentiation,
        "effects": list(effects or []),
        "last_updated": datetime.now(UTC).isoformat(),
    }
    cm = _client()
    try:
        await cm.put_concept_discovery_stack(user_id, work_id, payload)
    finally:
        await cm.aclose()
    log.info(
        "staging.save uid=%s inv=%s purpose_chars=%d components=%d effects=%d",
        user_id[:8],
        work_id[:8],
        len(purpose),
        len(payload["components"]),
        len(payload["effects"]),
    )
    return {"ok": True}
