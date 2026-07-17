"""CM-side tools — Actor 가 DRO tool step 으로 CM 자원을 쓰는 wrapper.

DRO 의 _exec_tool_call 이 `cm.*` 도구에 user_id/work_id 를 자동 주입.
파이프라인 params 에는 비즈니스 payload 만 명시.
"""

from __future__ import annotations

import logging
from typing import Any

from ...cm_client import CMClient
from .. import register

log = logging.getLogger(__name__)


def _client() -> CMClient:
    """CM client lazy 생성 — config 로딩 순서 보호."""
    from ...config import settings

    return CMClient(settings.CM_URL)


@register("cm.save_drawing_artifacts")
async def save_drawing_artifacts(
    drawing_id: str | None = None,
    numerals_payload: Any = None,
    dl_payload: Any = None,
    figure_payload: Any = None,
    user_id: str | None = None,
    work_id: str | None = None,
) -> dict[str, Any]:
    """P02.R13.SAVE_DRAWING_ARTIFACTS.step0.

    도면 1개의 artifacts (numerals + dl + figure) 를 CM 에 PUT.
    각 payload 는 None 일 수 있음 (해당 part 미저장).

    user_id / work_id 는 DRO 의 _exec_tool_call 이 자동 주입.
    """
    if not drawing_id:
        raise ValueError("drawing_id required")
    if not user_id or not work_id:
        raise ValueError(
            "user_id/work_id missing — DRO 가 자동 주입해야 함. "
            "tool category 가 'cm.*' 인지 확인."
        )

    cm = _client()
    saved: list[str] = []
    try:
        for part, payload in (
            ("numerals", numerals_payload),
            ("dl", dl_payload),
            ("figure", figure_payload),
        ):
            if payload is None:
                continue
            if not isinstance(payload, dict):
                raise ValueError(f"{part}_payload must be a dict, got {type(payload).__name__}")
            await cm.put_drawing_part(user_id, work_id, drawing_id, part, payload)
            saved.append(part)
    finally:
        await cm.aclose()

    return {
        "drawing_id": drawing_id,
        "saved_parts": saved,
    }


@register("cm.append_conversation")
async def append_conversation(
    message: Any = None,
    user_id: str | None = None,
    work_id: str | None = None,
) -> dict[str, Any]:
    """P01 의 self-contained save step — assistant turn 을 conversation.json 에 append.

    P01.R{10,20,21,40,41,42,43} 의 마지막 step 에서 LLM 이 만든 `assistant_turn`
    (role/content/meta dict) 을 단일 인자로 받아 그대로 conversation 에 누적.
    P02 등 다른 페르소나는 conversation 만 보고 자체 처리.

    `message`: {role: 'user'|'assistant', content: str, meta?: dict} — pipeline 의 placeholder 가
    이전 LLM step 의 `$.steps.<N>.assistant_turn` 전체 dict 를 그대로 전달.

    user_id / work_id 는 DRO 의 _exec_tool_call 이 자동 주입.
    """
    if not isinstance(message, dict):
        raise ValueError(f"message must be a dict, got {type(message).__name__}")
    role = message.get("role")
    content = message.get("content")
    if role not in ("user", "assistant"):
        raise ValueError(f"message.role must be 'user' or 'assistant', got {role!r}")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("message.content must be a non-empty string")
    if not user_id or not work_id:
        raise ValueError(
            "user_id/work_id missing — DRO 가 자동 주입해야 함. "
            "tool category 가 'cm.*' 인지 확인."
        )

    from datetime import UTC, datetime

    payload: dict[str, Any] = {
        "role": role,
        "content": content,
        "timestamp": message.get("timestamp") or datetime.now(UTC).isoformat(),
    }
    if message.get("meta") is not None:
        payload["meta"] = message["meta"]

    cm = _client()
    try:
        await cm.append_conversation(user_id, work_id, payload)
    finally:
        await cm.aclose()
    return {"appended": True, "role": role, "content_chars": len(content)}
