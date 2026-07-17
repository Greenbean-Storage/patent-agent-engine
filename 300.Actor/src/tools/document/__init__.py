"""Document parsing tool. PDF/docx 파싱 wrapper.

기존 01.Buddy/src/media_processor.py 패턴 참고. 의존성 (pypdf, python-docx) 설치
없이도 stub 동작 가능.
"""

from __future__ import annotations

import logging
from typing import Any

from .. import register

log = logging.getLogger(__name__)


@register("document.parse")
async def parse(
    media: str | None = None,
    media_ref: str | None = None,
    format: str = "auto",
    prompt: str | None = None,
) -> dict[str, Any]:
    """media S3 ref → 텍스트 추출. format 자동 감지 (확장자 기반).

    pipeline params_map keys: media / prompt (@pipelines/01.buddy/W01.R20).
    media_ref 는 legacy alias.
    """
    ref = media or media_ref or ""
    if not ref:
        return {"media": ref, "text": "", "note": "empty ref"}

    ext = ref.rsplit(".", 1)[-1].lower() if "." in ref else ""
    if format == "auto":
        format = {"pdf": "pdf", "docx": "docx", "txt": "text", "md": "text"}.get(ext, "text")

    return {
        "media": ref,
        "format": format,
        "text": "",
        "note": "stub — pdf/docx parsing requires pypdf/python-docx, install in next phase",
    }
