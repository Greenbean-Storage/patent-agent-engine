"""Vision IO + 도면 검수 tool. 기존 06.Inspector 에서 이전.

Gemini Vision API (Vertex AI) 의존. MODE != PRODUCTION 이면 stub.
"""

from __future__ import annotations

import logging
from typing import Any

from .. import register

log = logging.getLogger(__name__)


@register("vision.image_io")
async def image_io(media_ref: str) -> dict[str, Any]:
    """media S3 ref → bytes load + 기본 metadata."""
    from ...cm_client import get_cm_client

    get_cm_client()
    try:
        # media_ref = 미디어 S3 key (work 레벨). 단순화: ref 만 echo (stub).
        return {"media_ref": media_ref, "loaded": False, "note": "stub — full impl in next phase"}
    except Exception as e:  # noqa: BLE001
        return {"media_ref": media_ref, "error": str(e)}


@register("vision.review_drawing")
async def review_drawing(
    figure_b64: str,
    figure_mime: str = "image/png",
    prompt: str | None = None,
) -> dict[str, Any]:
    """도면 vision 검수 — Gemini API 미설정 시 stub.

    pipeline params_map keys: figure_b64 / figure_mime / prompt (@pipelines/06.inspector/W06.R00).
    """
    from ...config import settings

    if settings.LLM_MODE != "PRODUCTION":
        # overall_pass 는 vision 검수 결과 bool — password 아님
        return {
            "review": {"overall_pass": True, "comment": "stub review", "checks": []},  # nosec B105
            "note": "non-PRODUCTION mode — stub response",
        }
    try:
        from .reviewer import VisionReviewer
    except ImportError:
        # reviewer 미구현 — stub
        return {
            "review": {"overall_pass": True, "comment": "stub review", "checks": []},  # nosec B105
            "note": "vision reviewer not implemented — stub response",
        }
    try:
        rv = VisionReviewer()
        result = await rv.review(figure_b64=figure_b64, mime_type=figure_mime)
        return {"review": result}
    except Exception as e:  # noqa: BLE001
        log.warning("vision.review_drawing.error %s", e)
        return {"review": None, "error": str(e)}
