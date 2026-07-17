"""100.Nexus 새 트리(info/user/works) 응답 모델 — D6 타이핑.

additionalProperties 전역 정책 (A-3, C2):
  - **응답 = open** (`extra="allow"`) — 서버가 항목 추가해도 클라 codegen 안 깨짐(forward-compat).
  - **요청 = strict** (`extra="forbid"`) — 오타·잘못된 항목 거부.
  - **PII-0 응답 = forbid 보존** — 인증/계정 응답에 실명·이메일 부재를 *계약으로* 강제.
PII-0 forbid 대상: Authorize/Connect/Disconnect/AccountInfo/Alias.
구 `account.py`/`auth.py`(work_id·email·name 포함)는 재사용하지 않음.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

# ── info (전역) ──────────────────────────────────────────────────────────


class ProvidersResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    providers: list[str]


class AttributionsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    open_source: list[Any] = []
    ai_notice: str
    copyright: str


class HealthResponse(BaseModel):
    """GET /health — 라이브니스 + 현재 auth 모드 (B3)."""

    model_config = ConfigDict(extra="allow")
    status: str
    service: str | None = None
    auth_mode: Literal["open", "secure"]


# ── auth (federated 로그인) — PII 0 ────────────────────────────────────────


class AuthorizeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authorization_url: str
    state: str


class ConnectResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str
    connected: str


class DisconnectResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str
    disconnected: str


# ── account (프로필) — PII 0 (nickname=alias 만) ──────────────────────────


class AccountInfoResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")  # email/name 부재를 계약으로 강제
    user_id: str
    alias: str
    providers: list[str]


class AliasResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alias: str


# ── 요청 모델 (write) — A-3: 요청 = strict(forbid). B1 typed body. ──────────


class AliasUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alias: str


class MetaRenameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str


class ConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    state: str


# ── works (컬렉션·메타) ────────────────────────────────────────────────────


class WorkMaturitySnapshot(BaseModel):
    """works 목록/상세에 실리는 성숙도 요약(CMM 매핑). WS `WorkProgress`(실시간 진행 문구)와
    별개 — 동명 충돌 해소(A-8). drafting 단계 progress 는 미정의(null) — v1 한계."""

    model_config = ConfigDict(extra="allow")
    phase: str
    progress: float | None = None
    clarity: float | None = None
    completeness: float | None = None
    potential: float | None = None


class WorkCreateResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    work_id: str  # 201 성공 시 항상 존재 — handler 가 미반환 시 500 (위치 없는 201 금지)
    created_at: datetime | None = None


class WorkBriefItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    work_id: str
    title: str
    progress: WorkMaturitySnapshot
    last_activity_at: datetime | None = None
    created_at: datetime | None = None


class WorkBriefResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    items: list[WorkBriefItem]


class WorkEntryResponse(BaseModel):
    """work 진입점 — 가벼운 식별({work_id, title}). 하위 자원은 고정 URL 템플릿(A-9). 상세는 meta."""

    model_config = ConfigDict(extra="allow")
    work_id: str
    title: str


class WorkDetailResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    work_id: str
    title: str
    title_source: Literal["user", "auto"]
    progress: WorkMaturitySnapshot
    last_activity_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
