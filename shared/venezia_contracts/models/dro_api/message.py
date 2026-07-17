from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class MessageHistoryItem(BaseModel):
    """대화 이력의 1 turn — 사용자 발화·assistant 응답·시스템 알림 모두 같은 shape.

    `id` = work 내 안정 메시지 id (= conversation 내 0-based 위치, A-4). 페이징 커서·정렬·
    `message.reply.data.id` 와 동일 어휘. append-only 라 위치가 안정 → API 경계에서 파생(저장 X).
    `meta` 안에 `kind`, `roadmap_item_id` 등 부가 정보가 들어갈 수 있어 자유 dict.
    work_api.ThreadMessagesResponse 가 재사용 (live).
    """

    model_config = ConfigDict(extra="allow")

    id: int
    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: datetime
    meta: dict[str, Any] | None = None
