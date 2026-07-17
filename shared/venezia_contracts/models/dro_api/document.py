from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class DraftBuildResponse(BaseModel):
    """POST …/output/draft 응답.

    현재 IOM을 DOCX로 동기 변환해 200 결과를 반환하고, 완료 알림은 WS `output.ready`로
    별도 전달한다. IOM 작성 workflow와 장시간 비동기 job 모델은 별도 작성 단계 범위다.
    """

    model_config = ConfigDict(extra="allow")  # A-3: 응답 = open

    document_id: str
    filename: str
    size_bytes: int  # A-7: WS output.ready 와 동일 필드명(REST/WS 대칭)


class DraftPreviewResponse(BaseModel):
    """GET /api/v1/works/{work_id}/output/draft/preview 응답 — 미리보기 (마스킹된 형태).

    대부분 섹션은 string (단 `claims`·`sections_present` 는 string 배열). 백엔드가 일부
    substring 을 `---` 으로 대체해 보냄 (메타 5 + 과금 게이트 모델). 클라이언트는 그대로
    렌더. 어떤 영역을 가릴지는 백엔드 로직.

    `additionalProperties: allow` — 섹션 종류는 작성 단계 설계 진척에 따라 늘어남.
    """

    model_config = ConfigDict(extra="allow")

    title: str | None = None
    abstract: str | None = None
    technical_field: str | None = None
    background: str | None = None
    specification: str | None = None  # 본문 — 마스킹 적용
    claims: list[str] | None = None  # 청구항 — 본문 마스킹 적용
    sections_present: list[str] | None = None
