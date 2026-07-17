"""CM-side tools 전수 (invoke 단위) — 300.Actor/src/tools/cm/__init__.py.

대상 2 handler:
  - cm.save_drawing_artifacts — drawing artifacts (numerals/dl/figure) PUT.
    각 payload None=skip, dict 아님=ValueError, drawing_id/user_id/work_id 가드.
  - cm.append_conversation — assistant/user turn 을 conversation 에 append.
    message dict 가드, role allowlist, content non-empty, timestamp/meta 처리, id 가드.

전략: 모듈의 `_client()` 를 monkeypatch 해 AsyncMock CMClient 반환 — HTTP/config 우회.
put_drawing_part / append_conversation 호출 인자를 진짜 assert. aclose 가 finally 에서
항상 불리는지도 검증. register 데코레이터가 TOOLS 에 등록했는지 확인.

async 는 asyncio.run(...) (pytest-asyncio mark 없이; suite 패턴).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "300.Actor"))
sys.path.insert(0, str(ROOT / "shared"))

from src.tools import cm as cm_tools  # noqa: E402
from src.tools import get as tool_get  # noqa: E402

_U = "user-uuid"
_INV = "inv-uuid"


@pytest.fixture
def mock_cm(monkeypatch):
    """`_client()` 가 AsyncMock CMClient 를 반환하도록 교체. test 가 mock 을 직접 검사."""
    fake = AsyncMock()
    monkeypatch.setattr(cm_tools, "_client", lambda: fake)
    return fake


@pytest.fixture
def topology_env(monkeypatch):
    """settings.CM_URL 는 venezia_topology 가 topology.yaml 을 읽어 derive — host 에선
    TOPOLOGY_FILE env 필요. @deployment/topology.yaml 을 가리키고 lru_cache 초기화."""
    import venezia_topology as vt

    monkeypatch.setenv("TOPOLOGY_FILE", str(ROOT / "@deployment" / "topology.yaml"))
    vt._load.cache_clear()
    yield
    vt._load.cache_clear()


# ── registry ──────────────────────────────────────────────────────────────────


def test_handlers_registered():
    assert tool_get("cm.save_drawing_artifacts") is cm_tools.save_drawing_artifacts
    assert tool_get("cm.append_conversation") is cm_tools.append_conversation


# ── _client() (실제 한번 호출, config 경유) ─────────────────────────────────────


def test_client_builds_cmclient(monkeypatch, topology_env):
    """_client() 가 settings.CM_URL 로 CMClient 를 만든다 — 마지막 미커버 라인."""
    from src.config import settings

    captured: dict[str, str] = {}

    class _FakeCM:
        def __init__(self, base_url: str) -> None:
            captured["base_url"] = base_url

    # _client() 본문이 모듈 top-level 로 import 한 CMClient 를 부른다 → cm_tools.CMClient 교체.
    monkeypatch.setattr(cm_tools, "CMClient", _FakeCM)
    out = cm_tools._client()
    assert isinstance(out, _FakeCM)
    assert captured["base_url"] == settings.CM_URL


# ── save_drawing_artifacts ────────────────────────────────────────────────────


def test_save_drawing_all_parts(mock_cm):
    out = asyncio.run(
        cm_tools.save_drawing_artifacts(
            drawing_id="d1",
            numerals_payload={"n": 1},
            dl_payload={"d": 2},
            figure_payload={"f": 3},
            user_id=_U,
            work_id=_INV,
        )
    )
    assert out == {"drawing_id": "d1", "saved_parts": ["numerals", "dl", "figure"]}
    assert mock_cm.put_drawing_part.await_count == 3
    mock_cm.put_drawing_part.assert_any_await(_U, _INV, "d1", "numerals", {"n": 1})
    mock_cm.put_drawing_part.assert_any_await(_U, _INV, "d1", "dl", {"d": 2})
    mock_cm.put_drawing_part.assert_any_await(_U, _INV, "d1", "figure", {"f": 3})
    mock_cm.aclose.assert_awaited_once()


def test_save_drawing_skips_none_payloads(mock_cm):
    """numerals 만 줌 — dl/figure 는 None 분기로 continue, 저장 X."""
    out = asyncio.run(
        cm_tools.save_drawing_artifacts(
            drawing_id="d2",
            numerals_payload={"n": 1},
            user_id=_U,
            work_id=_INV,
        )
    )
    assert out == {"drawing_id": "d2", "saved_parts": ["numerals"]}
    assert mock_cm.put_drawing_part.await_count == 1
    mock_cm.put_drawing_part.assert_awaited_once_with(_U, _INV, "d2", "numerals", {"n": 1})
    mock_cm.aclose.assert_awaited_once()


def test_save_drawing_all_none_saves_nothing(mock_cm):
    out = asyncio.run(cm_tools.save_drawing_artifacts(drawing_id="d3", user_id=_U, work_id=_INV))
    assert out == {"drawing_id": "d3", "saved_parts": []}
    mock_cm.put_drawing_part.assert_not_awaited()
    mock_cm.aclose.assert_awaited_once()


def test_save_drawing_missing_drawing_id_raises(mock_cm):
    with pytest.raises(ValueError, match="drawing_id required"):
        asyncio.run(cm_tools.save_drawing_artifacts(user_id=_U, work_id=_INV))
    # 가드가 _client() 호출 전에 raise — mock 미사용
    mock_cm.put_drawing_part.assert_not_awaited()
    mock_cm.aclose.assert_not_awaited()


def test_save_drawing_missing_user_id_raises(mock_cm):
    with pytest.raises(ValueError, match="user_id/work_id missing"):
        asyncio.run(cm_tools.save_drawing_artifacts(drawing_id="d1", work_id=_INV))
    mock_cm.aclose.assert_not_awaited()


def test_save_drawing_missing_work_id_raises(mock_cm):
    with pytest.raises(ValueError, match="user_id/work_id missing"):
        asyncio.run(cm_tools.save_drawing_artifacts(drawing_id="d1", user_id=_U))
    mock_cm.aclose.assert_not_awaited()


def test_save_drawing_non_dict_payload_raises_and_closes(mock_cm):
    """payload 가 dict 아님 → ValueError, 그래도 finally 의 aclose 는 불린다."""
    with pytest.raises(ValueError, match="numerals_payload must be a dict, got str"):
        asyncio.run(
            cm_tools.save_drawing_artifacts(
                drawing_id="d1",
                numerals_payload="oops",
                user_id=_U,
                work_id=_INV,
            )
        )
    mock_cm.put_drawing_part.assert_not_awaited()
    mock_cm.aclose.assert_awaited_once()


# ── append_conversation ────────────────────────────────────────────────────────


def test_append_conversation_minimal(mock_cm):
    out = asyncio.run(
        cm_tools.append_conversation(
            message={"role": "assistant", "content": "hello there"},
            user_id=_U,
            work_id=_INV,
        )
    )
    assert out == {"appended": True, "role": "assistant", "content_chars": len("hello there")}
    mock_cm.append_conversation.assert_awaited_once()
    args = mock_cm.append_conversation.await_args.args
    assert args[0] == _U
    assert args[1] == _INV
    payload = args[2]
    assert payload["role"] == "assistant"
    assert payload["content"] == "hello there"
    assert isinstance(payload["timestamp"], str) and payload["timestamp"]
    assert "meta" not in payload
    mock_cm.aclose.assert_awaited_once()


def test_append_conversation_preserves_timestamp_and_meta(mock_cm):
    ts = "2026-06-04T00:00:00+00:00"
    meta = {"kind": "roadmap.answer"}
    out = asyncio.run(
        cm_tools.append_conversation(
            message={
                "role": "user",
                "content": "yes",
                "timestamp": ts,
                "meta": meta,
            },
            user_id=_U,
            work_id=_INV,
        )
    )
    assert out == {"appended": True, "role": "user", "content_chars": 3}
    payload = mock_cm.append_conversation.await_args.args[2]
    assert payload["timestamp"] == ts
    assert payload["meta"] == meta
    mock_cm.aclose.assert_awaited_once()


def test_append_conversation_non_dict_message_raises(mock_cm):
    with pytest.raises(ValueError, match="message must be a dict, got list"):
        asyncio.run(cm_tools.append_conversation(message=[], user_id=_U, work_id=_INV))
    mock_cm.append_conversation.assert_not_awaited()
    mock_cm.aclose.assert_not_awaited()


def test_append_conversation_bad_role_raises(mock_cm):
    with pytest.raises(ValueError, match="message.role must be"):
        asyncio.run(
            cm_tools.append_conversation(
                message={"role": "system", "content": "x"},
                user_id=_U,
                work_id=_INV,
            )
        )
    mock_cm.aclose.assert_not_awaited()


def test_append_conversation_empty_content_raises(mock_cm):
    with pytest.raises(ValueError, match="message.content must be a non-empty string"):
        asyncio.run(
            cm_tools.append_conversation(
                message={"role": "user", "content": "   "},
                user_id=_U,
                work_id=_INV,
            )
        )
    mock_cm.aclose.assert_not_awaited()


def test_append_conversation_non_string_content_raises(mock_cm):
    with pytest.raises(ValueError, match="message.content must be a non-empty string"):
        asyncio.run(
            cm_tools.append_conversation(
                message={"role": "user", "content": 123},
                user_id=_U,
                work_id=_INV,
            )
        )
    mock_cm.aclose.assert_not_awaited()


def test_append_conversation_missing_ids_raises(mock_cm):
    with pytest.raises(ValueError, match="user_id/work_id missing"):
        asyncio.run(
            cm_tools.append_conversation(
                message={"role": "user", "content": "hi"},
                work_id=_INV,
            )
        )
    mock_cm.append_conversation.assert_not_awaited()
    mock_cm.aclose.assert_not_awaited()


def test_append_conversation_closes_on_cm_error(mock_cm):
    """append_conversation 이 raise 해도 finally 의 aclose 는 불린다."""
    mock_cm.append_conversation.side_effect = RuntimeError("boom")
    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(
            cm_tools.append_conversation(
                message={"role": "user", "content": "hi"},
                user_id=_U,
                work_id=_INV,
            )
        )
    mock_cm.aclose.assert_awaited_once()
