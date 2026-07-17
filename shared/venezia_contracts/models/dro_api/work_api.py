"""200.DRO work-resource 응답 모델 — D6 타이핑 (phase / thread / estimate / media-list).

정밀 포맷은 기존 정밀 모델 재사용: 로드맵=`RoadmapItem`(8필드), 쓰레드=`MessageHistoryItem`,
성숙도=clarity/completeness/potential(미계산 시 nullable, raw CM `concept_*` alias 수용).
draft/media-upload 은 `document.py`/`upload.py` 재사용. 데이터 모델 `extra="allow"`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from .message import MessageHistoryItem
from .roadmap import RoadmapItem

# 노출 phase state 4값 (A-6 어휘). 내부 current_phase 2값과 별개.
WorkState = Literal["discovery", "ready", "drafting", "complete"]


class PhaseStateResponse(BaseModel):
    """GET·PATCH …/works/{id}/phase 응답. state ∈ discovery|ready|drafting|complete."""

    model_config = ConfigDict(extra="allow")
    state: WorkState


class ThreadMessagesResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    items: list[MessageHistoryItem] = []
    next_cursor: str | None = None


class RoadmapPullResponse(BaseModel):
    """top-level array 가 아니라 wrap. 각 item = 정밀 `RoadmapItem`(8필드)."""

    model_config = ConfigDict(extra="allow")
    items: list[RoadmapItem] = []


class RoadmapSubmitResponse(BaseModel):
    """답변 수락 ack. 내부 chain id 미노출(meta-5) — 진행은 WS 이벤트((user,work) 키 broadcast)."""

    model_config = ConfigDict(extra="allow")  # A-3: 응답 = open
    accepted: bool


class MaturityScoresOut(BaseModel):
    """성숙도 3 지표 — 미계산 시 null. 저장·표면 모두 짧은 키(A-2, alias 불요).
    의미: clarity=개념 명료성 · completeness=명세 완성도 · potential=특허성 잠재력."""

    model_config = ConfigDict(extra="allow")
    clarity: float | None = None
    completeness: float | None = None
    potential: float | None = None


class EstimateMaturityResponse(BaseModel):
    """CMM 현재값. shaped null — 3 필드 모두 **항상 존재(required)**, 값만 None/shaped(B10).

    overall_score·weights = scalar-or-null, scores = 항상 shaped 객체(하위 지표가 null) →
    프런트 형태 안정. handler 가 미계산 시에도 3 키를 모두 채운다.
    """

    model_config = ConfigDict(extra="allow")
    overall_score: float | None
    scores: MaturityScoresOut
    weights: dict[str, float] | None


class MediaItem(BaseModel):
    """GET .../media item — work 레벨 미디어 (S3 prefix 가 진실, 장부 없음).

    mime/size/last_modified 는 S3 가 보유 (Content-Type/Size/LastModified) — 종류 진실 = S3.
    """

    model_config = ConfigDict(extra="allow")
    media_id: str
    ext: str | None = None
    key: str
    size_bytes: int
    mime: str
    last_modified: datetime | None = None


class MediaListResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    items: list[MediaItem] = []


class MediaDownloadResponse(MediaItem):
    """GET .../media/{media_id} — 미디어 자원 표현 = MediaItem 메타 + presigned 다운로드 URL.

    바이트는 클라가 S3 에서 직접 GET (redirect 아님 — URL 을 본문으로 반환).
    """

    url: str
    ttl: int
