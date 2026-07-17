from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, RootModel


class RoadmapAnswer(BaseModel):
    model_config = ConfigDict(extra="allow")  # A-3: 응답(임베드) = open

    value: str | list[str]
    answered_at: datetime


class RoadmapSubmitRequest(BaseModel):
    """PATCH …/estimate/roadmap/{item_id} 요청 — 답변 값(B1). strict: 숫자·dict·혼합리스트 거부."""

    model_config = ConfigDict(extra="forbid", strict=True)  # A-3 요청=strict + 비-str 차단
    value: str | list[str]


class RoadmapItem(BaseModel):
    """P-D: top-level array 의 각 item (8 필드 strict).

    `id` 는 사이클 넘어가도 보존 (D 안 자연 누적의 핵심). 탐색 링크 없음(A-9) — 하위 자원 URL 은
    고정 템플릿으로 구성. CM 저장(UR)은 raw dict (8 필드).
    """

    model_config = ConfigDict(extra="allow")  # A-3: 응답 = open (8 필드 타이핑은 유지)

    id: str
    title: str
    description: str
    status: Literal["pending", "satisfied", "skipped"]
    priority: int
    input_type: Literal["chat", "selection", "checkbox", "keyword", "none"]
    options: list[str] | None = None
    answer: RoadmapAnswer | None = None


class RoadmapResponse(RootModel[list[RoadmapItem]]):
    """user-roadmap (UR) 모델 — P-D top-level JSON array.

    P-D: top-level JSON array. file-level meta (version/last_updated/overall_completeness) 없음.
    매 사이클 P02 director (step 6 update_roadmap + step 7 roadmap.persist) 가 전체 list 새로 작성.
    같은 id 의 item 은 보존 (D 안 자연 누적, list 자체가 시간선).

    아직 갱신 안 된 invention 은 빈 array `[]` 반환.
    """

    root: list[RoadmapItem]
