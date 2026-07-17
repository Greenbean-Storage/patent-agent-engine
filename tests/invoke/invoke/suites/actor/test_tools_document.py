"""document.parse 전수 (invoke 단위) — 300.Actor/src/tools/document/__init__.py.

대상 handler: document.parse — media S3 ref 에서 텍스트 추출 (현재 stub).
LLM/HTTP/CLI 의존 없음 — 순수 분기 (ref alias, 빈 ref, 확장자 → format 자동 감지).

검증:
  - register 데코레이터가 TOOLS 에 등록
  - media / media_ref alias (media 우선), 둘 다 없으면 empty-ref 분기
  - format="auto" 의 확장자 → format 매핑 (pdf/docx/txt/md/unknown/no-ext)
  - format 명시 (auto 아님) 시 자동 감지 우회
  - 반환 dict 형태 (media/format/text/note)

async 는 asyncio.run(...) (pytest-asyncio mark 없이; suite 패턴). 진짜 assert.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "300.Actor"))
sys.path.insert(0, str(ROOT / "shared"))

from src.tools import document as doc  # noqa: E402
from src.tools import get as tool_get  # noqa: E402


# ── registry ──────────────────────────────────────────────────────────────────


def test_handler_registered():
    assert tool_get("document.parse") is doc.parse


# ── empty ref ───────────────────────────────────────────────────────────────────


def test_parse_no_ref_returns_empty_note():
    out = asyncio.run(doc.parse())
    assert out == {"media": "", "text": "", "note": "empty ref"}


def test_parse_empty_string_ref_returns_empty_note():
    out = asyncio.run(doc.parse(media="", media_ref=""))
    assert out == {"media": "", "text": "", "note": "empty ref"}


# ── media / media_ref alias ───────────────────────────────────────────────────


def test_parse_media_takes_priority_over_media_ref():
    out = asyncio.run(doc.parse(media="s3://b/a.pdf", media_ref="s3://b/legacy.txt"))
    assert out["media"] == "s3://b/a.pdf"
    assert out["format"] == "pdf"


def test_parse_media_ref_legacy_alias_used_when_media_absent():
    out = asyncio.run(doc.parse(media_ref="s3://b/old.docx"))
    assert out["media"] == "s3://b/old.docx"
    assert out["format"] == "docx"


# ── format auto-detect by extension ────────────────────────────────────────────


def test_parse_auto_pdf():
    out = asyncio.run(doc.parse(media="x.pdf"))
    assert out["format"] == "pdf"


def test_parse_auto_docx():
    out = asyncio.run(doc.parse(media="x.docx"))
    assert out["format"] == "docx"


def test_parse_auto_txt_maps_to_text():
    out = asyncio.run(doc.parse(media="notes.txt"))
    assert out["format"] == "text"


def test_parse_auto_md_maps_to_text():
    out = asyncio.run(doc.parse(media="readme.md"))
    assert out["format"] == "text"


def test_parse_auto_unknown_ext_defaults_text():
    out = asyncio.run(doc.parse(media="archive.zip"))
    assert out["format"] == "text"


def test_parse_auto_no_extension_defaults_text():
    """확장자 구분자 '.' 없음 → ext='' → unknown → text."""
    out = asyncio.run(doc.parse(media="s3://bucket/noext"))
    assert out["format"] == "text"


def test_parse_uppercase_extension_normalized():
    """ext 는 lower() 되므로 .PDF 도 pdf."""
    out = asyncio.run(doc.parse(media="X.PDF"))
    assert out["format"] == "pdf"


# ── explicit format bypasses auto-detect ───────────────────────────────────────


def test_parse_explicit_format_overrides_extension():
    """format 명시(auto 아님) → 확장자 무시하고 그대로 유지."""
    out = asyncio.run(doc.parse(media="x.pdf", format="docx"))
    assert out["format"] == "docx"


# ── return shape (stub) ─────────────────────────────────────────────────────────


def test_parse_return_shape_is_stub():
    out = asyncio.run(doc.parse(media="x.pdf", prompt="describe"))
    assert out["text"] == ""
    assert "pypdf/python-docx" in out["note"]
    assert set(out) == {"media", "format", "text", "note"}
