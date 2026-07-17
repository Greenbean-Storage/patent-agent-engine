"""venezia_cm_client — CM HTTP base 공통부 (invoke 단위, D-4).

대상: shared/venezia_cm_client (`CMClientBase` + `dict_to_add_ops`).
전략: httpx.MockTransport 를 CMClientBase._client 에 주입 — 각 공통 메서드가 올바른 url(+pointer)
로 호출하고 404→None 정규화 하는지. 컨테이너 cm_client 는 이 base 를 상속(각 src suite 가 고유부).
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from venezia_cm_client import CMClientBase, dict_to_add_ops

_BASE = "http://cm-test:59400"
_U = "u-1"
_INV = "i-1"


def _client(handler) -> CMClientBase:
    c = CMClientBase(base_url=_BASE)
    c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return c


def _capturing(payload: Any, status: int = 200) -> tuple[dict, Any]:
    """path+params 기록 handler + 기록 dict 반환."""
    cap: dict[str, Any] = {}

    def h(req: httpx.Request) -> httpx.Response:
        cap["path"] = req.url.path
        cap["params"] = dict(req.url.params)
        return httpx.Response(status, json=payload) if status != 404 else httpx.Response(404)

    return cap, h


# ── dict_to_add_ops ──────────────────────────────────────────────────────────


def test_dict_to_add_ops_basic():
    ops = dict_to_add_ops({"output": {"text": "hi"}, "status": "done"})
    assert ops == [
        {"op": "add", "path": "/output", "value": {"text": "hi"}},
        {"op": "add", "path": "/status", "value": "done"},
    ]


def test_dict_to_add_ops_empty():
    assert dict_to_add_ops({}) == []


# ── __init__ / aclose ────────────────────────────────────────────────────────


def test_init_strips_trailing_slash_and_keeps_timeout():
    c = CMClientBase(base_url="http://cm/", timeout=12.0)
    assert c.base == "http://cm"
    assert c.timeout == 12.0


def test_aclose():
    c = _client(lambda req: httpx.Response(200, json={}))
    asyncio.run(c.aclose())


# ── _model_get (pointer 분기 + 404) ──────────────────────────────────────────


def test_model_get_root_no_params():
    cap, h = _capturing({"k": 1})
    out = asyncio.run(_client(h)._model_get(f"{_BASE}/x"))
    assert out == {"k": 1}
    assert cap["params"] == {}  # pointer="" → params 없음


def test_model_get_with_pointer():
    cap, h = _capturing("v")
    out = asyncio.run(_client(h)._model_get(f"{_BASE}/x", "/a/b"))
    assert out == "v"
    assert cap["params"] == {"pointer": "/a/b"}


def test_model_get_404_none():
    c = _client(lambda req: httpx.Response(404))
    assert asyncio.run(c._model_get(f"{_BASE}/x")) is None


# ── _get_or_none ─────────────────────────────────────────────────────────────


def test_get_or_none_ok():
    c = _client(lambda req: httpx.Response(200, json={"ok": True}))
    assert asyncio.run(c._get_or_none(f"{_BASE}/x")) == {"ok": True}


def test_get_or_none_404():
    c = _client(lambda req: httpx.Response(404))
    assert asyncio.run(c._get_or_none(f"{_BASE}/x")) is None


# ── 공통 model GET (url 정확성 — 세 컨테이너 동일) ───────────────────────────


def test_get_conversation_url():
    cap, h = _capturing([])
    asyncio.run(_client(h).get_conversation(_U, _INV))
    assert cap["path"] == f"/sessions/{_U}/{_INV}/runtime/00.dro/conversation"


def test_get_concept_maturity_model_url():
    cap, h = _capturing({})
    asyncio.run(_client(h).get_concept_maturity_model(_U, _INV))
    assert cap["path"] == f"/sessions/{_U}/{_INV}/models/concept-maturity-model"


def test_get_user_roadmap_url():
    cap, h = _capturing([])
    asyncio.run(_client(h).get_user_roadmap(_U, _INV))
    assert cap["path"] == f"/sessions/{_U}/{_INV}/models/user-roadmap"


def test_get_drawing_manifest_url():
    cap, h = _capturing({"drawings": []})
    out = asyncio.run(_client(h).get_drawing_manifest(_U, _INV))
    assert out == {"drawings": []}
    assert cap["path"] == f"/sessions/{_U}/{_INV}/drawings/manifest"


def test_get_drawing_manifest_404_none():
    c = _client(lambda req: httpx.Response(404))
    assert asyncio.run(c.get_drawing_manifest(_U, _INV)) is None
