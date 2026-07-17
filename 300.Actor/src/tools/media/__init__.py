"""Media tools — 사용자 첨부 multimedia 처리.

DRO tool step (POST /tool/{name}) 으로 호출. P01 Buddy 의 멀티모달 chain 들이 사용.

도구 2 종:
  - media_classifier.classify(media)         : MIME 기반 분류 (P01.R00.step0)
  - media_processor.image_describe(...)      : Gemini Vision → 이미지 설명 (P01.R11.step0)
  - media_processor.document_describe(...)   : PDF/docx → 텍스트 + LLM (P01.R20.step0)
  - media_processor.audio_describe(...)      : Audio → STT + LLM (P01.R21.step0)

media 객체 형식 (모든 tool 공통):
  {
    "data": <base64 string>,
    "mime_type": "image/jpeg" | "application/pdf" | "audio/wav" | ...,
    "filename": <str optional>,
  }

list 형 (classifier 가 받는 경우):
  [media_obj, media_obj, ...]
"""

from __future__ import annotations

from . import (
    classifier,  # noqa: F401  # @register("media_classifier.classify")
    processor,  # noqa: F401  # @register("media_processor.*")
)
