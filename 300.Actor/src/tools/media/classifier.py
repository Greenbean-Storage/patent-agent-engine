"""media_classifier.classify — MIME 기반 첨부 분류.

P01.R00.CHAT_CONVERSATION.step0 이 호출. 후속 chain 분기 단서.

output (classify_media-output schema):
  media_types: list[str]   # ["image"], ["document"], ["audio"], ["image","document"] 등
  intent_hint: str         # 분류 결과 요약 문장 (다음 chain 의 선택 단서)
"""

from __future__ import annotations

from typing import Any

from .. import register

# MIME prefix → 카테고리 매핑
_PREFIX_MAP: list[tuple[str, str]] = [
    ("image/", "image"),
    ("audio/", "audio"),
    ("video/", "video"),
]

# document subtype 명시 매핑
_DOCUMENT_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.ms-powerpoint",
    "text/plain",
    "text/markdown",
    "text/csv",
}


def _category_of(mime: str) -> str:
    if not isinstance(mime, str):
        return "unknown"
    m = mime.strip().lower()
    if m in _DOCUMENT_TYPES:
        return "document"
    for prefix, cat in _PREFIX_MAP:
        if m.startswith(prefix):
            return cat
    if m.startswith("text/") or m.startswith("application/"):
        return "document"
    return "unknown"


@register("media_classifier.classify")
async def classify(media: Any = None) -> dict[str, Any]:
    """media list 의 MIME 을 카테고리로 매핑.

    Args:
      media: list of {"data": ..., "mime_type": str, "filename": str?}
             단일 media object 도 허용 (single → list).
    Returns:
      {media_types: ["image", "document", ...], intent_hint: "..."}
    """
    if media is None:
        return {"media_types": [], "intent_hint": "no media attached"}

    items = media if isinstance(media, list) else [media]
    categories: list[str] = []
    for m in items:
        if not isinstance(m, dict):
            continue
        mime = m.get("mime_type") or m.get("content_type") or ""
        cat = _category_of(mime)
        if cat != "unknown" and cat not in categories:
            categories.append(cat)

    if not categories:
        intent = "no recognizable media"
    elif len(categories) == 1:
        intent = f"{categories[0]} attached"
    else:
        intent = f"multiple media types: {', '.join(categories)}"

    return {
        "media_types": categories,
        "intent_hint": intent,
    }
