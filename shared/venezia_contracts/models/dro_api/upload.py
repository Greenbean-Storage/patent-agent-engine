from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class PresignUploadResponse(BaseModel):
    """POST /api/v1/works/{id}/media 응답.

    브라우저가 `url` 로 multipart POST(`fields` + file)하여 **S3 에 직접 업로드** —
    바이트는 우리 서버(Nexus·CM)를 거치지 않는다. S3 가 presigned POST 정책으로
    크기(`max_file_bytes`)·MIME 을 강제. `media_id` 가 그 파일의 work 레벨 핸들
    (메시지와 무관, S3 prefix 가 진실).
    """

    model_config = ConfigDict(extra="allow")  # A-3: 응답 = open

    media_id: str
    key: str
    url: str
    fields: dict[str, str]
    max_file_bytes: int
    ttl: int


class PresignDownloadResponse(BaseModel):
    """presigned-get 의 bare 형태({url, ttl}).

    외부 `GET /api/v1/works/{id}/media/{media_id}` 는 `MediaDownloadResponse`(메타 + url)를
    쓴다. 클라이언트/Actor 가 `url` 로 S3 에서 **직접 GET** (presigned, 짧은 TTL) — 바이트는
    CM proxy 를 거치지 않는다.
    """

    model_config = ConfigDict(extra="allow")  # A-3: 응답 = open

    url: str
    ttl: int


class MediaUploadUrlRequest(BaseModel):
    """POST /api/v1/works/{id}/media 요청 — 올릴 파일의 이름(확장자 도출용)·MIME."""

    model_config = ConfigDict(extra="forbid")

    filename: str | None = None
    mime: str
