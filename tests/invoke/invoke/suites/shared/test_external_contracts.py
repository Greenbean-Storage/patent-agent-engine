"""invoke suite — 외부 API contract 모델 동작 검증 (shared venv).

`venezia_contracts.models.dro_api` 응답 모델이 D6/D9/A4 결정대로 동작하는지 단위 검증.
A5 체크포인트의 일회성 `python -c` 검증을 트랙(`make invoke`)으로 일반화한 것.
"""

from __future__ import annotations

import pydantic
import pytest
from venezia_contracts.models.dro_api.account_api import (
    AccountInfoResponse,
    AuthorizeResponse,
    WorkCreateResponse,
)
from venezia_contracts.models.dro_api.error import ErrorCode
from venezia_contracts.models.dro_api.message import MessageHistoryItem
from venezia_contracts.models.dro_api.roadmap import RoadmapItem
from venezia_contracts.models.dro_api.upload import (
    MediaUploadUrlRequest,
    PresignDownloadResponse,
    PresignUploadResponse,
)
from venezia_contracts.models.dro_api.work_api import (
    EstimateMaturityResponse,
    MediaItem,
    MediaListResponse,
    RoadmapPullResponse,
    RoadmapSubmitResponse,
    ThreadMessagesResponse,
)


def test_maturity_shaped_null():
    """미계산 시 shaped null — 3 필드 required(B10), 값만 None/shaped. handler 가 항상 채움."""
    m = EstimateMaturityResponse(
        overall_score=None,
        scores={"clarity": None, "completeness": None, "potential": None},
        weights=None,
    )
    assert m.overall_score is None and m.weights is None
    assert m.scores.clarity is None and m.scores.completeness is None and m.scores.potential is None
    # B10: 기본값 없음 → 필드 생략 시 required 위반 (handler 가 3 키 모두 제공해야 함)
    with pytest.raises(pydantic.ValidationError):
        EstimateMaturityResponse()
    print("✓ maturity shaped-null (required)")


def test_maturity_raw_cm_alias_normalizes():
    """raw CM 키(clarity 등) → 외부 짧은 이름(clarity)으로 정규화 (D6 정밀 + alias)."""
    m = EstimateMaturityResponse(
        overall_score=0.8,
        scores={
            "clarity": 0.9,
            "completeness": 0.7,
            "potential": 0.6,
        },
        weights=None,  # B10: required
    )
    assert m.scores.clarity == 0.9 and m.scores.completeness == 0.7 and m.scores.potential == 0.6
    assert m.model_dump()["scores"]["clarity"] == 0.9
    print("✓ maturity raw-CM alias 정규화")


def test_errorcode_no_internal_nouns():
    """외부 오류코드에 내부 명사(invention/iom/chain) 0 — D9 (메타 비식별)."""
    vals = {c.value for c in ErrorCode}
    assert "work_not_found" in vals and "content_not_ready" in vals
    assert "invention_not_found" not in vals and "iom_not_found" not in vals
    leaks = [v for v in vals if "invention" in v or v.startswith("iom") or "chain" in v]
    assert not leaks, f"내부 명사 누수: {leaks}"
    print(f"✓ ErrorCode 내부명사 0 ({len(vals)} codes)")


def test_pii0_account_auth_forbid_extra():
    """계정/인증 응답 extra=forbid → email/name 누수 계약 차단 (PII-0 강제)."""
    cases = [
        (AccountInfoResponse, {"user_id": "u", "alias": "a", "providers": []}),
        (AuthorizeResponse, {"authorization_url": "https://x", "state": "s"}),
    ]
    for model, ok in cases:
        model(**ok)  # valid
        with pytest.raises(pydantic.ValidationError):
            model(**{**ok, "email": "x@y.z"})  # PII extra 거부
    print("✓ PII-0 forbid (email 거부) — account/auth 응답")


def test_presign_upload_response_shape():
    """업로드 발급 응답 = presigned S3 직접 POST 핸들 (media_id + url + fields + 정책)."""
    r = PresignUploadResponse(
        media_id="m1",
        key="sessions/u/w/media/m1.png",
        url="https://s3/bucket",
        fields={"key": "sessions/u/w/media/m1.png", "Content-Type": "image/png"},
        max_file_bytes=20971520,
        ttl=600,
    )
    assert r.media_id == "m1" and r.fields["Content-Type"] == "image/png"
    fields = set(PresignUploadResponse.model_fields)
    # A-9: HAL `_links` 제거 — 탐색 링크 필드 없음. presigned 계약 필드만.
    assert fields == {"media_id", "key", "url", "fields", "max_file_bytes", "ttl"}
    # A-3: 응답 = open(extra allow) — 추가 키 수용(forward-compat), 선언 필드는 그대로
    r2 = PresignUploadResponse(
        media_id="m1", key="k", url="u", fields={}, max_file_bytes=1, ttl=1, upload_id="x"
    )
    assert r2.media_id == "m1"
    print("✓ PresignUploadResponse presigned 핸들")


def test_presign_download_response_shape():
    """다운로드 발급 응답 = presigned GET url + ttl (CM proxy 없음)."""
    r = PresignDownloadResponse(url="https://s3/get", ttl=300)
    assert r.url == "https://s3/get" and r.ttl == 300
    assert set(PresignDownloadResponse.model_fields) == {"url", "ttl"}
    # A-3: 응답 = open(extra allow) — 추가 키 수용(forward-compat), 선언 필드는 그대로
    r2 = PresignDownloadResponse(url="u", ttl=1, media_id="m")
    assert r2.url == "u" and r2.ttl == 1
    print("✓ PresignDownloadResponse presigned GET")


def test_media_upload_url_request_optional_filename():
    """업로드 요청 = mime 필수 + filename 선택(확장자 도출용)."""
    r = MediaUploadUrlRequest(mime="image/png")
    assert r.filename is None and r.mime == "image/png"
    assert MediaUploadUrlRequest(filename="a.png", mime="image/png").filename == "a.png"
    with pytest.raises(pydantic.ValidationError):
        MediaUploadUrlRequest()  # mime 필수
    with pytest.raises(pydantic.ValidationError):
        MediaUploadUrlRequest(mime="image/png", extra_key="x")  # extra=forbid
    print("✓ MediaUploadUrlRequest mime 필수 · filename 선택")


def test_media_list_items_precise():
    """media list item = work 레벨 MediaItem 정밀 모델 (S3 가 진실 — mime/size/last_modified)."""
    r = MediaListResponse(
        items=[
            {
                "media_id": "m1",
                "ext": "png",
                "key": "sessions/u/w/media/m1.png",
                "size_bytes": 123,
                "mime": "image/png",
                "last_modified": "2026-01-01T00:00:00Z",
            }
        ]
    )
    assert isinstance(r.items[0], MediaItem)
    assert r.items[0].media_id == "m1" and r.items[0].size_bytes == 123
    empty = MediaListResponse()
    assert empty.items == []
    # ext/last_modified nullable (S3 가 미보유 가능)
    bare = MediaItem(media_id="m2", key="k", size_bytes=0, mime="application/pdf")
    assert bare.ext is None and bare.last_modified is None
    print("✓ MediaListResponse/MediaItem 정밀")


def test_roadmap_submit_no_chains():
    """roadmap/submit 응답 = {accepted} only — 내부 chain id 미노출 (A4 meta-5)."""
    assert set(RoadmapSubmitResponse.model_fields) == {"accepted"}
    print("✓ RoadmapSubmitResponse no-chains")


def test_precise_item_models_reused():
    """로드맵/쓰레드 item = 정밀 모델 (loose dict 아님) — D6 정밀 타이핑."""
    r = RoadmapPullResponse(
        items=[
            {
                "id": "q1",
                "title": "t",
                "description": "d",
                "status": "pending",
                "priority": 1,
                "input_type": "chat",
            }
        ]
    )
    assert isinstance(r.items[0], RoadmapItem)
    t = ThreadMessagesResponse(
        items=[{"id": 0, "role": "user", "content": "hi", "timestamp": "2026-01-01T00:00:00Z"}]
    )
    assert isinstance(t.items[0], MessageHistoryItem)
    print("✓ 정밀 item 모델 (RoadmapItem/MessageHistoryItem) 재사용")


def test_work_create_required_workid():
    """works 생성(201) work_id 는 필수·non-null — handler 가 미반환 시 500(위치 없는 201 금지)."""
    assert WorkCreateResponse(work_id="w1").work_id == "w1"
    with pytest.raises(pydantic.ValidationError):
        WorkCreateResponse(work_id=None)  # None 거부
    with pytest.raises(pydantic.ValidationError):
        WorkCreateResponse()  # 누락 거부
    print("✓ WorkCreateResponse.work_id required (non-null)")
