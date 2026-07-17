"""vision tool 전수 (invoke 단위) — 300.Actor/src/tools/vision/__init__.py.

대상 2 handler:
  - vision.image_io(media_ref)  — get_cm_client() 호출 + stub echo dict.
  - vision.review_drawing(...)  — LLM_MODE 분기:
      * != PRODUCTION → stub review.
      * PRODUCTION + reviewer 미구현 (ImportError) → stub.
      * PRODUCTION + reviewer OK → VisionReviewer().review() 결과.
      * PRODUCTION + reviewer.review() 예외 → {review:None, error}.

전략:
  - image_io: cm_client.get_cm_client 를 monkeypatch (실 HTTP 우회). echo 결과 assert.
  - review_drawing: src.config.settings.LLM_MODE 를 monkeypatch 로 PRODUCTION 토글.
    reviewer.py 는 repo 에 없음 → 기본 ImportError 분기. 성공/예외 분기는 fake
    `src.tools.vision.reviewer` 모듈을 sys.modules 에 주입해 import 를 성공시킨 뒤 검증.

async 는 asyncio.run(...) (pytest-asyncio mark 없이; suite 패턴).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock

import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "300.Actor"))
sys.path.insert(0, str(ROOT / "shared"))

from src.tools import get as tool_get  # noqa: E402
from src.tools import vision  # noqa: E402

_REVIEWER_MOD = "src.tools.vision.reviewer"


@pytest.fixture
def production_mode(monkeypatch):
    """src.config.settings.LLM_MODE 를 PRODUCTION 으로."""
    from src.config import settings

    monkeypatch.setattr(settings, "LLM_MODE", "PRODUCTION")
    yield settings


@pytest.fixture
def no_reviewer_module():
    """reviewer 모듈이 import 캐시에 없도록 보장 (ImportError 분기 결정성)."""
    prev = sys.modules.pop(_REVIEWER_MOD, None)
    yield
    if prev is not None:  # pragma: no cover — 테스트 환경엔 reviewer 부재
        sys.modules[_REVIEWER_MOD] = prev


def _inject_fake_reviewer(reviewer_cls) -> None:
    """fake `src.tools.vision.reviewer` 모듈을 sys.modules 에 주입 — import 성공시킴."""
    mod = ModuleType(_REVIEWER_MOD)
    mod.VisionReviewer = reviewer_cls  # type: ignore[attr-defined]
    sys.modules[_REVIEWER_MOD] = mod


# ── registry ──────────────────────────────────────────────────────────────────


def test_handlers_registered():
    assert tool_get("vision.image_io") is vision.image_io
    assert tool_get("vision.review_drawing") is vision.review_drawing


# ── image_io ────────────────────────────────────────────────────────────────────


def test_image_io_returns_stub_and_calls_cm(monkeypatch):
    import src.cm_client as cm_client_mod

    called: dict[str, bool] = {"hit": False}

    def _fake_get_cm():
        called["hit"] = True
        return object()

    monkeypatch.setattr(cm_client_mod, "get_cm_client", _fake_get_cm)
    out = asyncio.run(vision.image_io("s3://bucket/media-0.png"))
    assert out == {
        "media_ref": "s3://bucket/media-0.png",
        "loaded": False,
        "note": "stub — full impl in next phase",
    }
    assert called["hit"] is True


# ── review_drawing: non-PRODUCTION ───────────────────────────────────────────────


def test_review_drawing_non_production_stub(monkeypatch):
    from src.config import settings

    monkeypatch.setattr(settings, "LLM_MODE", "FIXTURE")
    out = asyncio.run(vision.review_drawing(figure_b64="QUJD"))
    assert out == {
        "review": {"overall_pass": True, "comment": "stub review", "checks": []},
        "note": "non-PRODUCTION mode — stub response",
    }


def test_review_drawing_non_production_default_mime_and_prompt(monkeypatch):
    """figure_mime / prompt default 값으로 호출해도 동일 stub."""
    from src.config import settings

    monkeypatch.setattr(settings, "LLM_MODE", "FIXTURE")
    out = asyncio.run(
        vision.review_drawing(figure_b64="QUJD", figure_mime="image/png", prompt=None)
    )
    assert out["note"] == "non-PRODUCTION mode — stub response"


# ── review_drawing: PRODUCTION + reviewer 미구현 (ImportError) ────────────────────


def test_review_drawing_production_no_reviewer_stub(production_mode, no_reviewer_module):
    out = asyncio.run(vision.review_drawing(figure_b64="QUJD"))
    assert out == {
        "review": {"overall_pass": True, "comment": "stub review", "checks": []},
        "note": "vision reviewer not implemented — stub response",
    }


# ── review_drawing: PRODUCTION + reviewer 성공 ────────────────────────────────────


def test_review_drawing_production_reviewer_success(production_mode):
    captured: dict = {}

    class _FakeReviewer:
        async def review(self, figure_b64, mime_type):
            captured["figure_b64"] = figure_b64
            captured["mime_type"] = mime_type
            return {"overall_pass": False, "comment": "numerals missing"}

    _inject_fake_reviewer(_FakeReviewer)
    try:
        out = asyncio.run(
            vision.review_drawing(figure_b64="Zmln==", figure_mime="image/jpeg", prompt="check")
        )
    finally:
        sys.modules.pop(_REVIEWER_MOD, None)

    assert out == {"review": {"overall_pass": False, "comment": "numerals missing"}}
    assert captured == {"figure_b64": "Zmln==", "mime_type": "image/jpeg"}


def test_review_drawing_production_reviewer_review_is_awaited(production_mode):
    """VisionReviewer().review 가 실제 await 되는지 AsyncMock 으로 확인."""
    review_mock = AsyncMock(return_value={"overall_pass": True, "checks": ["scale"]})

    class _FakeReviewer:
        def __init__(self) -> None:
            self.review = review_mock

    _inject_fake_reviewer(_FakeReviewer)
    try:
        out = asyncio.run(vision.review_drawing(figure_b64="QUJD"))
    finally:
        sys.modules.pop(_REVIEWER_MOD, None)

    assert out == {"review": {"overall_pass": True, "checks": ["scale"]}}
    review_mock.assert_awaited_once_with(figure_b64="QUJD", mime_type="image/png")


# ── review_drawing: PRODUCTION + reviewer.review() 예외 ──────────────────────────


def test_review_drawing_production_reviewer_raises(production_mode):
    class _BoomReviewer:
        async def review(self, figure_b64, mime_type):
            raise RuntimeError("vision api down")

    _inject_fake_reviewer(_BoomReviewer)
    try:
        out = asyncio.run(vision.review_drawing(figure_b64="QUJD"))
    finally:
        sys.modules.pop(_REVIEWER_MOD, None)

    assert out == {"review": None, "error": "vision api down"}


def test_review_drawing_production_constructor_raises(production_mode):
    """VisionReviewer() 생성자 예외도 except 분기 (rv = VisionReviewer() 라인)."""

    class _BadCtor:
        def __init__(self) -> None:
            raise RuntimeError("ctor failed")

    _inject_fake_reviewer(_BadCtor)
    try:
        out = asyncio.run(vision.review_drawing(figure_b64="QUJD"))
    finally:
        sys.modules.pop(_REVIEWER_MOD, None)

    assert out == {"review": None, "error": "ctor failed"}
