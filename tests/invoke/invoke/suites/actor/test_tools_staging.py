"""staging.save 전수 (invoke 단위) — 300.Actor/src/tools/staging/__init__.py.

대상 handler: staging.save — ConceptDiscoveryStack 7 필드를 받아 CM PUT (mock cm).
계산 없음 — list 정규화 + last_updated 추가 후 put_concept_discovery_stack.

검증:
  - register 데코레이터가 TOOLS 에 등록
  - user_id/work_id 가드 (둘 중 하나라도 없으면 ValueError, PUT 안 함)
  - 7 필드 payload 구성 (None → [] 정규화, scalar 그대로) + last_updated 추가
  - put_concept_discovery_stack 가 올바른 인자로 한번 호출
  - aclose 가 finally 에서 항상 (성공·실패 모두) 호출
  - _client() 가 settings.CM_URL 로 CMClient 생성 (마지막 미커버 라인)

전략: 모듈의 `_client()` 를 monkeypatch 해 AsyncMock CMClient 반환 — HTTP/config 우회.

async 는 asyncio.run(...) (pytest-asyncio mark 없이; suite 패턴). 진짜 assert.
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

from src.tools import get as tool_get  # noqa: E402
from src.tools import staging as st  # noqa: E402

_U = "user-uuid-12345678"
_INV = "inv-uuid-87654321"


@pytest.fixture
def mock_cm(monkeypatch):
    """`_client()` 가 AsyncMock CMClient 를 반환하도록 교체. test 가 mock 을 직접 검사."""
    fake = AsyncMock()
    monkeypatch.setattr(st, "_client", lambda: fake)
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


def test_handler_registered():
    assert tool_get("staging.save") is st.save


# ── _client() (config 경유, 마지막 미커버 라인) ─────────────────────────────────


def test_client_builds_cmclient(monkeypatch, topology_env):
    """_client() 가 settings.CM_URL 로 CMClient 를 만든다."""
    from src.config import settings

    captured: dict[str, str] = {}

    class _FakeCM:
        def __init__(self, base_url: str) -> None:
            captured["base_url"] = base_url

    monkeypatch.setattr(st, "CMClient", _FakeCM)
    out = st._client()
    assert isinstance(out, _FakeCM)
    assert captured["base_url"] == settings.CM_URL


# ── user_id / work_id 가드 ────────────────────────────────────────────────


def test_save_missing_user_id_raises(mock_cm):
    with pytest.raises(ValueError, match="user_id/work_id missing"):
        asyncio.run(st.save(purpose="p", work_id=_INV))
    mock_cm.put_concept_discovery_stack.assert_not_awaited()
    mock_cm.aclose.assert_not_awaited()


def test_save_missing_work_id_raises(mock_cm):
    with pytest.raises(ValueError, match="user_id/work_id missing"):
        asyncio.run(st.save(purpose="p", user_id=_U))
    mock_cm.put_concept_discovery_stack.assert_not_awaited()
    mock_cm.aclose.assert_not_awaited()


def test_save_both_missing_raises(mock_cm):
    with pytest.raises(ValueError, match="user_id/work_id missing"):
        asyncio.run(st.save())
    mock_cm.put_concept_discovery_stack.assert_not_awaited()


# ── happy path: full 7 fields ──────────────────────────────────────────────────


def test_save_full_payload(mock_cm):
    out = asyncio.run(
        st.save(
            purpose="solve X",
            components=["c1", "c2"],
            operation_sequence=["s1"],
            causality=["a→b"],
            embodiments=["e1"],
            differentiation="novel approach",
            effects=["faster"],
            user_id=_U,
            work_id=_INV,
        )
    )
    assert out == {"ok": True}
    mock_cm.put_concept_discovery_stack.assert_awaited_once()
    mock_cm.aclose.assert_awaited_once()

    call_user, call_inv, payload = mock_cm.put_concept_discovery_stack.await_args.args
    assert call_user == _U
    assert call_inv == _INV
    assert payload["purpose"] == "solve X"
    assert payload["components"] == ["c1", "c2"]
    assert payload["operation_sequence"] == ["s1"]
    assert payload["causality"] == ["a→b"]
    assert payload["embodiments"] == ["e1"]
    assert payload["differentiation"] == "novel approach"
    assert payload["effects"] == ["faster"]
    assert "last_updated" in payload and isinstance(payload["last_updated"], str)
    assert set(payload) == {
        "purpose",
        "components",
        "operation_sequence",
        "causality",
        "embodiments",
        "differentiation",
        "effects",
        "last_updated",
    }


# ── None list 정규화 → [] ───────────────────────────────────────────────────────


def test_save_none_lists_normalized_to_empty(mock_cm):
    """모든 list 인자 생략(None) → [] 로 정규화, scalar 는 기본값 빈 string."""
    out = asyncio.run(st.save(user_id=_U, work_id=_INV))
    assert out == {"ok": True}
    _u, _i, payload = mock_cm.put_concept_discovery_stack.await_args.args
    assert payload["purpose"] == ""
    assert payload["differentiation"] == ""
    for key in (
        "components",
        "operation_sequence",
        "causality",
        "embodiments",
        "effects",
    ):
        assert payload[key] == []


def test_save_copies_list_inputs(mock_cm):
    """payload 의 list 는 입력 list 의 사본 (list(...) 정규화) — 동일 객체 아님."""
    comps = ["c1"]
    asyncio.run(st.save(components=comps, user_id=_U, work_id=_INV))
    _u, _i, payload = mock_cm.put_concept_discovery_stack.await_args.args
    assert payload["components"] == ["c1"]
    assert payload["components"] is not comps


# ── PUT 실패해도 finally aclose ────────────────────────────────────────────────


def test_save_closes_on_cm_error(mock_cm):
    mock_cm.put_concept_discovery_stack.side_effect = RuntimeError("cm down")
    with pytest.raises(RuntimeError, match="cm down"):
        asyncio.run(st.save(purpose="p", user_id=_U, work_id=_INV))
    mock_cm.aclose.assert_awaited_once()
