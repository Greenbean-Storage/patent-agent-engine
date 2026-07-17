"""media_classifier.classify 전수 (invoke 단위) — 300.Actor/src/tools/media/classifier.py.

대상:
  - _category_of(mime) — MIME → 카테고리 (document allowlist / prefix map / fallback / unknown).
  - classify(media)    — single/list media 의 MIME 을 카테고리로 매핑 + intent_hint 문장.

전략: 순수 함수 — 외부 의존 0. register 데코레이터가 TOOLS 에 등록했는지 + 모든 분기
(None / non-string mime / document subtype / prefix image|audio|video / text|application fallback /
unknown / single→list / non-dict skip / 중복 제거 / 0·1·N 카테고리 intent) 를 진짜 assert.

async 는 asyncio.run(...) (pytest-asyncio mark 없이; suite 패턴).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "300.Actor"))

from src.tools import get as tool_get  # noqa: E402
from src.tools.media import classifier as mc  # noqa: E402


# ── registry ──────────────────────────────────────────────────────────────────


def test_handler_registered():
    assert tool_get("media_classifier.classify") is mc.classify


# ── _category_of ────────────────────────────────────────────────────────────────


def test_category_of_non_string_returns_unknown():
    assert mc._category_of(None) == "unknown"  # type: ignore[arg-type]
    assert mc._category_of(123) == "unknown"  # type: ignore[arg-type]


def test_category_of_document_subtype_exact():
    assert mc._category_of("application/pdf") == "document"
    assert mc._category_of("text/csv") == "document"
    # strip + lower 정규화 분기
    assert mc._category_of("  APPLICATION/PDF  ") == "document"


def test_category_of_prefix_image_audio_video():
    assert mc._category_of("image/png") == "image"
    assert mc._category_of("audio/wav") == "audio"
    assert mc._category_of("video/mp4") == "video"


def test_category_of_text_fallback_to_document():
    # text/markdown 은 allowlist 에 있지만 미등록 text/* 도 fallback → document
    assert mc._category_of("text/x-rst") == "document"


def test_category_of_application_fallback_to_document():
    # _DOCUMENT_TYPES 미등록 application/* 는 마지막 startswith fallback → document
    assert mc._category_of("application/zip") == "document"


def test_category_of_unknown():
    assert mc._category_of("font/woff2") == "unknown"
    assert mc._category_of("") == "unknown"


# ── classify ────────────────────────────────────────────────────────────────────


def test_classify_none_media():
    out = asyncio.run(mc.classify(None))
    assert out == {"media_types": [], "intent_hint": "no media attached"}


def test_classify_default_arg_is_none():
    # 인자 없이 호출 — media=None default
    out = asyncio.run(mc.classify())
    assert out == {"media_types": [], "intent_hint": "no media attached"}


def test_classify_single_media_object_wrapped_to_list():
    out = asyncio.run(mc.classify({"mime_type": "image/jpeg"}))
    assert out == {"media_types": ["image"], "intent_hint": "image attached"}


def test_classify_uses_content_type_when_no_mime_type():
    out = asyncio.run(mc.classify({"content_type": "application/pdf"}))
    assert out == {"media_types": ["document"], "intent_hint": "document attached"}


def test_classify_list_dedupes_categories():
    media = [
        {"mime_type": "image/png"},
        {"mime_type": "image/jpeg"},  # 중복 image — categories 에 한번만
        {"mime_type": "application/pdf"},
    ]
    out = asyncio.run(mc.classify(media))
    assert out["media_types"] == ["image", "document"]
    assert out["intent_hint"] == "multiple media types: image, document"


def test_classify_skips_non_dict_items():
    media = [{"mime_type": "audio/wav"}, "not-a-dict", 42, None]
    out = asyncio.run(mc.classify(media))
    assert out == {"media_types": ["audio"], "intent_hint": "audio attached"}


def test_classify_missing_mime_defaults_empty_string_unknown():
    # mime_type / content_type 둘 다 없음 → "" → unknown → 제외
    out = asyncio.run(mc.classify([{"filename": "x.bin"}]))
    assert out == {"media_types": [], "intent_hint": "no recognizable media"}


def test_classify_all_unknown_gives_no_recognizable():
    out = asyncio.run(mc.classify([{"mime_type": "font/woff2"}]))
    assert out == {"media_types": [], "intent_hint": "no recognizable media"}
