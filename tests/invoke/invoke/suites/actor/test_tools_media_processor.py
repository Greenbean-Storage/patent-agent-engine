"""media_processor 전수 (invoke 단위) — 300.Actor/src/tools/media/processor.py.

대상:
  - _decode_media(media)  — dict 가드 / data·mime 누락 / bytes·bytearray / base64 str / 잘못된 type.
  - _describe(...)        — decode → mime prefix 검증 → prompt 검증 → Gemini async/sync 호출
                            → resp.text or candidates.parts.text 추출.
  - image_describe / document_describe / audio_describe — allowed_prefixes wrapper.

전략: google.genai SDK 의 client 를 mock — llm.client.get_gemini_client 를 monkeypatch 해
fake client 반환. fake.aio.models.generate_content 는 AsyncMock. sync fallback 분기는
aio attr 접근이 AttributeError 를 던지게 만들어 탄다. genai.types 는 실제 SDK 사용 (Actor venv
에 설치됨) — Part/Blob/Content 가 실제로 생성되는지까지 호출이 통과하면 확인됨.

async 는 asyncio.run(...) (pytest-asyncio mark 없이; suite 패턴).
"""

from __future__ import annotations

import asyncio
import base64
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "300.Actor"))

from src.tools import get as tool_get  # noqa: E402
from src.tools.media import processor as mp  # noqa: E402

_PNG = base64.b64encode(b"\x89PNG\r\n").decode()


class _FakeAioClient:
    """aio.models.generate_content (async) 를 가진 fake gemini client."""

    def __init__(self, resp, capture: dict | None = None) -> None:
        cap = capture if capture is not None else {}

        async def _gen(model, contents):
            cap["model"] = model
            cap["contents"] = contents
            return resp

        self.aio = SimpleNamespace(
            models=SimpleNamespace(generate_content=AsyncMock(side_effect=_gen))
        )


class _SyncOnlyClient:
    """aio 접근 시 AttributeError → sync fallback 분기를 타게 함."""

    def __init__(self, resp) -> None:
        self._resp = resp

        def _gen(model, contents):
            return self._resp

        self.models = SimpleNamespace(generate_content=_gen)

    def __getattr__(self, name):
        if name == "aio":
            raise AttributeError("no aio in this SDK version")
        raise AttributeError(name)


@pytest.fixture
def patch_client(monkeypatch):
    """llm.client.get_gemini_client 를 교체하는 헬퍼 반환."""

    def _install(client):
        import src.llm.client as client_mod

        monkeypatch.setattr(client_mod, "get_gemini_client", lambda: client)

    return _install


# ── registry ──────────────────────────────────────────────────────────────────


def test_handlers_registered():
    assert tool_get("media_processor.image_describe") is mp.image_describe
    assert tool_get("media_processor.document_describe") is mp.document_describe
    assert tool_get("media_processor.audio_describe") is mp.audio_describe


# ── _decode_media ────────────────────────────────────────────────────────────────


def test_decode_media_non_dict_raises():
    with pytest.raises(ValueError, match="media must be a dict, got list"):
        mp._decode_media([])


def test_decode_media_missing_data_raises():
    with pytest.raises(ValueError, match="media.data missing"):
        mp._decode_media({"mime_type": "image/png"})


def test_decode_media_missing_mime_raises():
    with pytest.raises(ValueError, match="media.mime_type missing"):
        mp._decode_media({"data": _PNG})


def test_decode_media_bytes_passthrough():
    binary, mime = mp._decode_media({"data": b"\x00\x01", "mime_type": "image/png"})
    assert binary == b"\x00\x01"
    assert mime == "image/png"


def test_decode_media_bytearray_passthrough():
    binary, mime = mp._decode_media({"data": bytearray(b"\x02\x03"), "content_type": "image/jpeg"})
    assert binary == b"\x02\x03"
    assert isinstance(binary, bytes)
    assert mime == "image/jpeg"


def test_decode_media_base64_string_decoded():
    binary, mime = mp._decode_media({"data": _PNG, "mime_type": "image/png"})
    assert binary == b"\x89PNG\r\n"
    assert mime == "image/png"


def test_decode_media_bad_data_type_raises():
    with pytest.raises(ValueError, match="media.data must be base64 string or bytes, got int"):
        mp._decode_media({"data": 12345, "mime_type": "image/png"})


# ── _describe (mime/prompt 가드) ─────────────────────────────────────────────────


def test_describe_disallowed_mime_raises(patch_client):
    # mime 검증은 client 호출 전 — patch 없이도 raise 하지만, 분기 격리 위해 patch 설치
    patch_client(_FakeAioClient(SimpleNamespace(text="x")))
    with pytest.raises(ValueError, match="not allowed; expected one of"):
        asyncio.run(
            mp._describe(
                {"data": _PNG, "mime_type": "audio/wav"}, "p", allowed_prefixes=("image/",)
            )
        )


def test_describe_empty_prompt_raises(patch_client):
    patch_client(_FakeAioClient(SimpleNamespace(text="x")))
    with pytest.raises(ValueError, match="prompt required"):
        asyncio.run(
            mp._describe(
                {"data": _PNG, "mime_type": "image/png"}, "   ", allowed_prefixes=("image/",)
            )
        )


def test_describe_non_string_prompt_raises(patch_client):
    patch_client(_FakeAioClient(SimpleNamespace(text="x")))
    with pytest.raises(ValueError, match="prompt required"):
        asyncio.run(
            mp._describe(
                {"data": _PNG, "mime_type": "image/png"}, None, allowed_prefixes=("image/",)
            )
        )


# ── _describe (성공 — async / sync fallback / text 추출) ─────────────────────────


def test_describe_async_resp_text():
    cap: dict = {}

    async def _run():
        import src.llm.client as client_mod

        client_mod.get_gemini_client = lambda: _FakeAioClient(SimpleNamespace(text="hello"), cap)
        return await mp._describe(
            {"data": _PNG, "mime_type": "image/png"}, "describe", allowed_prefixes=("image/",)
        )

    out = asyncio.run(_run())
    assert out == {
        "description": "hello",
        "mime_type": "image/png",
        "bytes": len(b"\x89PNG\r\n"),
        "model": "gemini-3.1-pro-preview",
    }
    assert cap["model"] == "gemini-3.1-pro-preview"
    # contents 가 genai Content 리스트로 합성됨
    assert len(cap["contents"]) == 1


def test_describe_candidates_parts_concatenation(monkeypatch):
    """resp.text 가 falsy → candidates.parts 의 text 들을 join."""
    import src.llm.client as client_mod

    resp = SimpleNamespace(
        text="",
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(
                    parts=[
                        SimpleNamespace(text="foo "),
                        SimpleNamespace(text="bar"),
                        SimpleNamespace(text=None),  # falsy 는 skip
                    ]
                )
            ),
            SimpleNamespace(content=None),  # content None → parts iter 안전
        ],
    )
    monkeypatch.setattr(client_mod, "get_gemini_client", lambda: _FakeAioClient(resp))
    out = asyncio.run(
        mp._describe({"data": _PNG, "mime_type": "image/png"}, "go", allowed_prefixes=("image/",))
    )
    assert out["description"] == "foo bar"


def test_describe_no_text_no_candidates_empty(monkeypatch):
    """resp.text 없음 + candidates None → description '' ."""
    import src.llm.client as client_mod

    resp = SimpleNamespace(text=None, candidates=None)
    monkeypatch.setattr(client_mod, "get_gemini_client", lambda: _FakeAioClient(resp))
    out = asyncio.run(
        mp._describe({"data": _PNG, "mime_type": "image/png"}, "go", allowed_prefixes=("image/",))
    )
    assert out["description"] == ""


def test_describe_sync_fallback_when_no_aio(monkeypatch):
    """client.aio 가 AttributeError → sync client.models.generate_content fallback."""
    import src.llm.client as client_mod

    resp = SimpleNamespace(text="synced")
    monkeypatch.setattr(client_mod, "get_gemini_client", lambda: _SyncOnlyClient(resp))
    out = asyncio.run(
        mp._describe({"data": _PNG, "mime_type": "image/png"}, "go", allowed_prefixes=("image/",))
    )
    assert out["description"] == "synced"


# ── public wrappers (allowed_prefixes 배선) ──────────────────────────────────────


def test_image_describe_allows_image(monkeypatch):
    import src.llm.client as client_mod

    monkeypatch.setattr(
        client_mod, "get_gemini_client", lambda: _FakeAioClient(SimpleNamespace(text="img"))
    )
    out = asyncio.run(mp.image_describe({"data": _PNG, "mime_type": "image/png"}, "p"))
    assert out["description"] == "img"


def test_image_describe_rejects_non_image(monkeypatch):
    import src.llm.client as client_mod

    monkeypatch.setattr(
        client_mod, "get_gemini_client", lambda: _FakeAioClient(SimpleNamespace(text="x"))
    )
    with pytest.raises(ValueError, match="not allowed"):
        asyncio.run(mp.image_describe({"data": _PNG, "mime_type": "application/pdf"}, "p"))


def test_document_describe_allows_application_and_text(monkeypatch):
    import src.llm.client as client_mod

    monkeypatch.setattr(
        client_mod, "get_gemini_client", lambda: _FakeAioClient(SimpleNamespace(text="doc"))
    )
    out = asyncio.run(mp.document_describe({"data": _PNG, "mime_type": "application/pdf"}, "p"))
    assert out["description"] == "doc"
    out2 = asyncio.run(mp.document_describe({"data": _PNG, "mime_type": "text/plain"}, "p"))
    assert out2["description"] == "doc"


def test_audio_describe_allows_audio(monkeypatch):
    import src.llm.client as client_mod

    monkeypatch.setattr(
        client_mod, "get_gemini_client", lambda: _FakeAioClient(SimpleNamespace(text="aud"))
    )
    out = asyncio.run(mp.audio_describe({"data": _PNG, "mime_type": "audio/wav"}, "p"))
    assert out["description"] == "aud"


def test_wrappers_default_prompt_empty_raises(monkeypatch):
    """prompt None default → "" → prompt required (decode 먼저 통과해야 도달)."""
    import src.llm.client as client_mod

    monkeypatch.setattr(
        client_mod, "get_gemini_client", lambda: _FakeAioClient(SimpleNamespace(text="x"))
    )
    with pytest.raises(ValueError, match="prompt required"):
        asyncio.run(mp.image_describe({"data": _PNG, "mime_type": "image/png"}))
