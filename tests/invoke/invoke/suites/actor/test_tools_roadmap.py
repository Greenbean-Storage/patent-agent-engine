"""roadmap.persist 전수 (invoke 단위) — 300.Actor/src/tools/roadmap/__init__.py.

대상 handler: roadmap.persist — user-roadmap.json (top-level array) CM PUT (mock cm).
WS push 는 DRO 책임이라 이 모듈에 없음 — tool 은 형식 검증 + CM PUT + {ok,count} 반환만.

검증:
  - _validate_item: dict 강제 / 필수 8 필드 / unknown 필드 / status enum / input_type enum /
    satisfied↔answer 정합 / pending·skipped↔answer null 정합
  - 중복 id 가드
  - user_id/work_id 가드 + items None/non-list 가드
  - 빈 list 도 통과 (count=0)
  - put_user_roadmap 가 올바른 인자(user_id/work_id/items array)로 한번 + aclose finally
  - _client() 가 settings.CM_URL 로 CMClient 생성 (마지막 미커버 라인)

전략: 모듈의 `_client()` 를 monkeypatch 해 AsyncMock CMClient 반환 — HTTP/config 우회.

async 는 asyncio.run(...) (pytest-asyncio mark 없이; suite 패턴).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "300.Actor"))
sys.path.insert(0, str(ROOT / "shared"))

from src.tools import get as tool_get  # noqa: E402
from src.tools import roadmap as rm  # noqa: E402

_U = "user-uuid-12345678"
_INV = "inv-uuid-87654321"


def _item(**overrides: Any) -> dict[str, Any]:
    """완전한 8-field roadmap item (overrides 로 개별 교체)."""
    base: dict[str, Any] = {
        "id": "r1",
        "title": "What problem?",
        "description": "Describe the problem.",
        "status": "pending",
        "priority": 1,
        "input_type": "chat",
        "options": [],
        "answer": None,
    }
    base.update(overrides)
    return base


@pytest.fixture
def mock_cm(monkeypatch):
    """`_client()` 가 AsyncMock CMClient 를 반환하도록 교체. test 가 mock 을 직접 검사."""
    fake = AsyncMock()
    monkeypatch.setattr(rm, "_client", lambda: fake)
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
    assert tool_get("roadmap.persist") is rm.persist


def test_const_sets():
    assert "answer" in rm._REQUIRED_FIELDS
    assert rm._STATUS_VALUES == frozenset({"pending", "satisfied", "skipped"})
    assert rm._INPUT_TYPES == frozenset({"chat", "selection", "checkbox", "keyword", "none"})


# ── _client() (config 경유, 마지막 미커버 라인) ─────────────────────────────────


def test_client_builds_cmclient(monkeypatch, topology_env):
    """_client() 가 settings.CM_URL 로 CMClient 를 만든다."""
    from src.config import settings

    captured: dict[str, str] = {}

    class _FakeCM:
        def __init__(self, base_url: str) -> None:
            captured["base_url"] = base_url

    monkeypatch.setattr(rm, "CMClient", _FakeCM)
    out = rm._client()
    assert isinstance(out, _FakeCM)
    assert captured["base_url"] == settings.CM_URL


# ── _validate_item (순수) ─────────────────────────────────────────────────────


def test_validate_item_ok_pending():
    # 예외 없이 통과 (return None)
    assert rm._validate_item(_item(), 0) is None


def test_validate_item_ok_satisfied_with_answer():
    assert rm._validate_item(_item(status="satisfied", answer="my answer"), 0) is None


def test_validate_item_ok_skipped_null_answer():
    assert rm._validate_item(_item(status="skipped", answer=None), 0) is None


def test_validate_item_non_dict_raises():
    with pytest.raises(ValueError, match=r"items\[2\] must be a dict, got list"):
        rm._validate_item([], 2)


def test_validate_item_missing_fields_raises():
    bad = _item()
    del bad["title"]
    del bad["options"]
    with pytest.raises(ValueError, match=r"items\[0\] missing fields: \['options', 'title'\]"):
        rm._validate_item(bad, 0)


def test_validate_item_unknown_fields_raises():
    bad = _item()
    bad["extra_a"] = 1
    bad["extra_b"] = 2
    with pytest.raises(ValueError, match=r"items\[1\] unknown fields: \['extra_a', 'extra_b'\]"):
        rm._validate_item(bad, 1)


def test_validate_item_bad_status_raises():
    with pytest.raises(ValueError, match=r"items\[0\].status invalid: 'done'"):
        rm._validate_item(_item(status="done"), 0)


def test_validate_item_bad_input_type_raises():
    with pytest.raises(ValueError, match=r"items\[0\].input_type invalid: 'voice'"):
        rm._validate_item(_item(input_type="voice"), 0)


def test_validate_item_satisfied_null_answer_raises():
    with pytest.raises(ValueError, match=r"items\[3\].status=satisfied but answer is null"):
        rm._validate_item(_item(status="satisfied", answer=None), 3)


def test_validate_item_pending_non_null_answer_raises():
    with pytest.raises(ValueError, match=r"items\[0\].status=pending but answer is not null"):
        rm._validate_item(_item(status="pending", answer="oops"), 0)


def test_validate_item_skipped_non_null_answer_raises():
    with pytest.raises(ValueError, match=r"items\[0\].status=skipped but answer is not null"):
        rm._validate_item(_item(status="skipped", answer="x"), 0)


# ── persist happy path ───────────────────────────────────────────────────────


def test_persist_single_item(mock_cm):
    items = [_item()]
    out = asyncio.run(rm.persist(items=items, user_id=_U, work_id=_INV))
    assert out == {"ok": True, "count": 1}
    mock_cm.put_user_roadmap.assert_awaited_once_with(_U, _INV, items)
    mock_cm.aclose.assert_awaited_once()


def test_persist_multiple_mixed_status(mock_cm):
    items = [
        _item(id="r1", status="pending", answer=None),
        _item(id="r2", status="satisfied", answer="yes"),
        _item(id="r3", status="skipped", answer=None),
    ]
    out = asyncio.run(rm.persist(items=items, user_id=_U, work_id=_INV))
    assert out == {"ok": True, "count": 3}
    # array 그대로 PUT (top-level array, 변형 없음).
    mock_cm.put_user_roadmap.assert_awaited_once_with(_U, _INV, items)
    mock_cm.aclose.assert_awaited_once()


def test_persist_empty_list_ok(mock_cm):
    out = asyncio.run(rm.persist(items=[], user_id=_U, work_id=_INV))
    assert out == {"ok": True, "count": 0}
    mock_cm.put_user_roadmap.assert_awaited_once_with(_U, _INV, [])
    mock_cm.aclose.assert_awaited_once()


def test_persist_all_input_types_and_statuses(mock_cm):
    """input_type / status enum 전 조합이 통과하는지 (검증 통과 경로)."""
    items = [
        _item(id="a", input_type="chat", status="pending", answer=None),
        _item(id="b", input_type="selection", status="satisfied", answer="opt"),
        _item(id="c", input_type="checkbox", status="skipped", answer=None),
        _item(id="d", input_type="keyword", status="pending", answer=None),
        _item(id="e", input_type="none", status="satisfied", answer=["x"]),
    ]
    out = asyncio.run(rm.persist(items=items, user_id=_U, work_id=_INV))
    assert out == {"ok": True, "count": 5}


# ── id 가드 / list 가드 ───────────────────────────────────────────────────────


def test_persist_missing_user_id_raises(mock_cm):
    with pytest.raises(ValueError, match="user_id/work_id missing"):
        asyncio.run(rm.persist(items=[_item()], work_id=_INV))
    mock_cm.put_user_roadmap.assert_not_awaited()
    mock_cm.aclose.assert_not_awaited()


def test_persist_missing_work_id_raises(mock_cm):
    with pytest.raises(ValueError, match="user_id/work_id missing"):
        asyncio.run(rm.persist(items=[_item()], user_id=_U))
    mock_cm.aclose.assert_not_awaited()


def test_persist_items_none_raises(mock_cm):
    with pytest.raises(ValueError, match=r"items required \(top-level array\)"):
        asyncio.run(rm.persist(items=None, user_id=_U, work_id=_INV))
    mock_cm.put_user_roadmap.assert_not_awaited()


def test_persist_items_non_list_raises(mock_cm):
    with pytest.raises(ValueError, match="items must be a list, got dict"):
        asyncio.run(rm.persist(items={"id": "r1"}, user_id=_U, work_id=_INV))
    mock_cm.put_user_roadmap.assert_not_awaited()


# ── 검증이 persist 안에서 잡는 분기 ────────────────────────────────────────────


def test_persist_invalid_item_raises_before_put(mock_cm):
    with pytest.raises(ValueError, match=r"items\[0\].status invalid"):
        asyncio.run(rm.persist(items=[_item(status="nope")], user_id=_U, work_id=_INV))
    mock_cm.put_user_roadmap.assert_not_awaited()
    mock_cm.aclose.assert_not_awaited()


def test_persist_duplicate_id_raises(mock_cm):
    items = [_item(id="dup"), _item(id="dup")]
    with pytest.raises(ValueError, match=r"items\[1\].id duplicate: 'dup'"):
        asyncio.run(rm.persist(items=items, user_id=_U, work_id=_INV))
    mock_cm.put_user_roadmap.assert_not_awaited()


# ── PUT 실패해도 finally aclose ───────────────────────────────────────────────────


def test_persist_closes_on_cm_error(mock_cm):
    mock_cm.put_user_roadmap.side_effect = RuntimeError("cm down")
    with pytest.raises(RuntimeError, match="cm down"):
        asyncio.run(rm.persist(items=[_item()], user_id=_U, work_id=_INV))
    mock_cm.aclose.assert_awaited_once()
