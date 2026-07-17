"""client-facing REST 경로 빌더 — 핸드빌드 f-string drift 방지(단일 출처).

`router.py` 의 `@router` decorator path 와 동일해야 한다. output draft 는 현재 **단일 고정
route**(`/output/draft`) — document_id-주소형 다중출력은 future. event_mapper 의 output.ready
URL 이 실 route 와 어긋나지 않게 여기서 합성(C10).
"""

from __future__ import annotations


def output_draft_url(work_id: str) -> str:
    """출원서 draft 다운로드 — `GET /api/v1/works/{work_id}/output/draft` 와 동일."""
    return f"/api/v1/works/{work_id}/output/draft"


def output_draft_preview_url(work_id: str) -> str:
    """출원서 draft preview — `GET /api/v1/works/{work_id}/output/draft/preview` 와 동일."""
    return f"/api/v1/works/{work_id}/output/draft/preview"
