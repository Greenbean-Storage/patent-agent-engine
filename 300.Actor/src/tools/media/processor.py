"""media_processor — Gemini multimodal SDK (Vertex AI) 로 image/document/audio → 자연어 설명.

호출 패턴: P01.R10/R20/R21 의 step0 (per-media describe step) 이 호출.
사용 모델: gemini-3.1-pro-preview (P1 Buddy 와 동일, Vertex AI global endpoint).

media 객체 형식:
  {"data": <base64 str>, "mime_type": str, "filename": str?}

prompt 는 호출자가 지정 (파이프라인 params 에 직접 명시).
"""

from __future__ import annotations

import base64
import logging
from typing import Any

from .. import register

log = logging.getLogger(__name__)


def _describe_model() -> str:
    """media describe 용 모델 — engine.config tools.media_describe.model (SoT)."""
    from ... import engine_config

    return str(engine_config.tools()["media_describe"]["model"])


def _decode_media(media: Any) -> tuple[bytes, str]:
    """media dict 에서 (binary_bytes, mime_type) 추출.

    raise ValueError: media 형식 불일치 또는 data 누락.
    """
    if not isinstance(media, dict):
        raise ValueError(f"media must be a dict, got {type(media).__name__}")
    raw = media.get("data")
    mime = media.get("mime_type") or media.get("content_type")
    if not raw:
        raise ValueError("media.data missing (expected base64 string or bytes)")
    if not mime:
        raise ValueError("media.mime_type missing")
    if isinstance(raw, bytes | bytearray):
        return bytes(raw), mime
    if isinstance(raw, str):
        return base64.b64decode(raw), mime
    raise ValueError(f"media.data must be base64 string or bytes, got {type(raw).__name__}")


async def _describe(media: Any, prompt: str, allowed_prefixes: tuple[str, ...]) -> dict[str, Any]:
    """Gemini multimodal 1-shot describe.

    allowed_prefixes: ('image/',) | ('application/', 'text/') | ('audio/',) 등 — 호출자 의도 검증.
    """
    binary, mime = _decode_media(media)
    if not any(mime.lower().startswith(p) for p in allowed_prefixes):
        raise ValueError(
            f"media.mime_type '{mime}' not allowed; expected one of {allowed_prefixes}"
        )
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt required")

    # lazy import — google.genai SDK 는 Actor 컨테이너에만 설치됨 (host pip 없음)
    from google.genai import types as genai_types

    from ...llm.client import get_gemini_client

    client = get_gemini_client()
    parts = [
        genai_types.Part(inline_data=genai_types.Blob(mime_type=mime, data=binary)),
        genai_types.Part(text=prompt),
    ]
    contents = [genai_types.Content(role="user", parts=parts)]

    # SDK 의 async generate_content
    try:
        resp = await client.aio.models.generate_content(model=_describe_model(), contents=contents)
    except AttributeError:
        # async API 없으면 sync fallback (loop 없이 호출은 위험하지만 SDK 버전 안전망)
        resp = client.models.generate_content(model=_describe_model(), contents=contents)

    # Extract text from response
    text = ""
    if hasattr(resp, "text") and resp.text:
        text = resp.text
    else:
        for c in getattr(resp, "candidates", None) or []:
            content = getattr(c, "content", None)
            for p in getattr(content, "parts", None) or []:
                t = getattr(p, "text", None)
                if t:
                    text += t

    return {
        "description": text,
        "mime_type": mime,
        "bytes": len(binary),
        "model": _describe_model(),
    }


@register("media_processor.image_describe")
async def image_describe(media: Any = None, prompt: str | None = None) -> dict[str, Any]:
    """이미지 1장 → 자연어 설명. P01.R11.IMAGE_SINGLE_ANALYZE.step0."""
    return await _describe(media, prompt or "", allowed_prefixes=("image/",))


@register("media_processor.document_describe")
async def document_describe(media: Any = None, prompt: str | None = None) -> dict[str, Any]:
    """문서 1개 (PDF/docx/txt) → 자연어 설명. P01.R20.DOCUMENT_ANALYZE.step0.

    Gemini 가 PDF 를 inline_data 로 직접 받음 (별도 PDF parser 불필요).
    """
    return await _describe(
        media,
        prompt or "",
        allowed_prefixes=("application/", "text/"),
    )


@register("media_processor.audio_describe")
async def audio_describe(media: Any = None, prompt: str | None = None) -> dict[str, Any]:
    """오디오 1개 → 자연어 설명 (STT + 의미 요약). P01.R21.AUDIO_ANALYZE.step0.

    Gemini 가 audio inline_data 를 native 처리 (별도 Whisper 등 불필요).
    """
    return await _describe(media, prompt or "", allowed_prefixes=("audio/",))
