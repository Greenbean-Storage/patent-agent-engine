"""300.Actor cm_client — CM HTTP wrapper 전수 (invoke 단위).

대상: 300.Actor/src/cm_client.py (CMClient 전 메서드 + get_cm_client).
전략: httpx.MockTransport(handler) 를 CMClient._client 에 주입 — handler 가 method+url 로
canned 응답을 돌려준다. 각 wrapper 메서드가 (1) 올바른 method+url(+body/params) 로 호출하고
(2) 응답을 올바르게 반환·파싱하며 (3) 404→None / raise_for_status 분기를 타는지 진짜 assert.

dro/test_cm_client.py 의 MockTransport 패턴을 따르되 Actor cm_client 시그니처에 맞춤.
async 는 asyncio.run(...) 로 (pytest-asyncio mark 없이; 기존 suite 패턴).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "300.Actor"))

from src.cm_client import CMClient, get_cm_client  # noqa: E402

_BASE = "http://cm-test:59400"
_U = "user-uuid"
_INV = "inv-uuid"


class _Capture:
    """handler 가 받은 마지막 request 의 핵심 필드를 보관 (assert 용)."""

    def __init__(self) -> None:
        self.method: str | None = None
        self.path: str | None = None
        self.params: dict[str, str] = {}
        self.json_body: Any = None
        self.raw: bytes = b""


def _make_client(handler, capture: _Capture | None = None) -> CMClient:
    """MockTransport 주입된 CMClient. handler(request)->Response. capture 시 요청 기록."""
    cap = capture or _Capture()

    def _wrapped(request: httpx.Request) -> httpx.Response:
        cap.method = request.method
        cap.path = request.url.path
        cap.params = dict(request.url.params)
        cap.raw = request.content
        try:
            cap.json_body = httpx.Response(200, content=request.content).json()
        except Exception:  # noqa: BLE001 — non-JSON 요청
            cap.json_body = None
        return handler(request)

    client = CMClient(base_url=_BASE)
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(_wrapped))
    return client


def _ok(payload: Any) -> httpx.Response:
    return httpx.Response(200, json=payload)


@pytest.fixture
def topology_env(monkeypatch):
    """settings.CM_URL 는 venezia_topology 가 topology.yaml 을 읽어 derive — host 에선
    TOPOLOGY_FILE env 필요. @deployment/topology.yaml 을 가리키고 lru_cache 초기화."""
    import venezia_topology as vt

    monkeypatch.setenv("TOPOLOGY_FILE", str(ROOT / "@deployment" / "topology.yaml"))
    vt._load.cache_clear()
    yield
    vt._load.cache_clear()


# ── 생성자 / aclose / get_cm_client ───────────────────────────────────────────


def test_init_strips_trailing_slash():
    c = CMClient(base_url="http://cm:1/")
    assert c.base == "http://cm:1"


def test_init_default_base_from_settings(topology_env):
    from src.config import settings

    c = CMClient()
    assert c.base == settings.CM_URL.rstrip("/")


def test_aclose_closes_client():
    c = _make_client(lambda r: _ok({}))

    async def _run():
        await c.aclose()
        assert c._client.is_closed

    asyncio.run(_run())


def test_get_cm_client_singleton(topology_env):
    import src.cm_client as mod

    mod._default = None
    a = get_cm_client()
    b = get_cm_client()
    assert a is b
    assert isinstance(a, CMClient)
    mod._default = None


# ── RT (runtime/{persona}/{cid}/rts/{rt_id}) ─────────────────────────────────


def test_get_rt():
    cap = _Capture()
    c = _make_client(lambda r: _ok({"rt_id": "rt7", "status": "pending"}), cap)
    out = asyncio.run(c.get_rt(_U, _INV, 6, "ch4", "rt7"))
    assert out == {"rt_id": "rt7", "status": "pending"}
    assert cap.method == "GET"
    assert cap.path == f"/sessions/{_U}/{_INV}/runtime/06.inspector/ch4/rts/rt7"


def test_get_rt_raises():
    c = _make_client(lambda r: httpx.Response(404))
    # get_rt has no 404→None branch: 404 must raise.
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(c.get_rt(_U, _INV, 1, "ch5", "rtX"))


def test_patch_rt_sends_add_ops():
    cap = _Capture()
    c = _make_client(lambda r: _ok({"status": "succeeded"}), cap)
    fields = {"output": {"text": "ok"}, "status": "succeeded"}
    out = asyncio.run(c.patch_rt(_U, _INV, 1, "ch5", "rt2", fields))
    assert out == {"status": "succeeded"}
    assert cap.method == "PATCH"
    assert cap.path == f"/sessions/{_U}/{_INV}/runtime/01.buddy/ch5/rts/rt2"
    assert cap.json_body == [
        {"op": "add", "path": "/output", "value": {"text": "ok"}},
        {"op": "add", "path": "/status", "value": "succeeded"},
    ]


def test_patch_rt_raises():
    c = _make_client(lambda r: httpx.Response(422))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(c.patch_rt(_U, _INV, 1, "ch5", "rt2", {"status": "x"}))


# ── agent_state ──────────────────────────────────────────────────────────────


def test_get_agent_state():
    cap = _Capture()
    c = _make_client(lambda r: _ok({"vendor": "gemini", "items": [{"author": "user"}]}), cap)
    out = asyncio.run(c.get_agent_state(_U, _INV, 2, "ch1"))
    assert out == {"vendor": "gemini", "items": [{"author": "user"}]}
    assert cap.method == "GET"
    assert cap.path == f"/sessions/{_U}/{_INV}/runtime/02.director/ch1/agent_state"


def test_get_agent_state_raises():
    c = _make_client(lambda r: httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(c.get_agent_state(_U, _INV, 2, "ch1"))


def test_put_agent_state_sends_envelope_verbatim():
    """state(envelope) 통째 PUT — 구 {"messages": ...} wrap 폐기 (컨텍스트 ②)."""
    cap = _Capture()
    c = _make_client(lambda r: _ok({"ok": True}), cap)
    env = {"schema_version": 1, "vendor": "openai", "model": "o3", "items": [{"role": "user"}]}
    out = asyncio.run(c.put_agent_state(_U, _INV, 3, "ch2", env))
    assert out == {"ok": True}
    assert cap.method == "PUT"
    assert cap.path == f"/sessions/{_U}/{_INV}/runtime/03.finder/ch2/agent_state"
    assert cap.json_body == env


def test_put_agent_state_raises():
    c = _make_client(lambda r: httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(c.put_agent_state(_U, _INV, 3, "ch2", {"items": []}))


# ── trail ────────────────────────────────────────────────────────────────────


def test_append_trail():
    cap = _Capture()
    c = _make_client(lambda r: _ok({}), cap)
    event = {"event": "rt_started", "rt_id": "rt1"}
    out = asyncio.run(c.append_trail(_U, _INV, 4, "ch2", event))
    assert out is None
    assert cap.method == "POST"
    assert cap.path == f"/sessions/{_U}/{_INV}/runtime/04.thinker/ch2/trail"
    assert cap.json_body == event


def test_append_trail_raises():
    c = _make_client(lambda r: httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(c.append_trail(_U, _INV, 4, "ch2", {"e": 1}))


def test_get_trail_parses_jsonl_skipping_blank_and_bad():
    cap = _Capture()
    body = '{"event":"a","rt_id":"r1"}\n   \n{"event":"b"}\nNOT_JSON\n'
    c = _make_client(lambda r: httpx.Response(200, text=body), cap)
    out = asyncio.run(c.get_trail(_U, _INV, 5, "ch3"))
    assert out == [{"event": "a", "rt_id": "r1"}, {"event": "b"}]
    assert cap.method == "GET"
    assert cap.path == f"/sessions/{_U}/{_INV}/runtime/05.crafter/ch3/trail"


def test_get_trail_404_returns_empty():
    c = _make_client(lambda r: httpx.Response(404))
    assert asyncio.run(c.get_trail(_U, _INV, 1, "ch1")) == []


def test_get_trail_empty_text_returns_empty():
    c = _make_client(lambda r: httpx.Response(200, text=""))
    assert asyncio.run(c.get_trail(_U, _INV, 1, "ch1")) == []


def test_get_trail_other_error_raises():
    c = _make_client(lambda r: httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(c.get_trail(_U, _INV, 1, "ch1"))


# ── conversation (00.dro) ────────────────────────────────────────────────────


def test_append_conversation():
    cap = _Capture()
    c = _make_client(lambda r: _ok({}), cap)
    msg = {"role": "user", "content": "hello"}
    out = asyncio.run(c.append_conversation(_U, _INV, msg))
    assert out is None
    assert cap.method == "POST"
    assert cap.path == f"/sessions/{_U}/{_INV}/runtime/00.dro/conversation/append"
    assert cap.json_body == msg


def test_append_conversation_raises():
    c = _make_client(lambda r: httpx.Response(422))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(c.append_conversation(_U, _INV, {"x": 1}))


def test_get_conversation_with_pointer():
    cap = _Capture()
    c = _make_client(lambda r: _ok({"messages": []}), cap)
    out = asyncio.run(c.get_conversation(_U, _INV, pointer="/messages"))
    assert out == {"messages": []}
    assert cap.method == "GET"
    assert cap.path == f"/sessions/{_U}/{_INV}/runtime/00.dro/conversation"
    assert cap.params == {"pointer": "/messages"}


def test_get_conversation_root_no_params():
    cap = _Capture()
    c = _make_client(lambda r: _ok({"messages": [1]}), cap)
    out = asyncio.run(c.get_conversation(_U, _INV))
    assert out == {"messages": [1]}
    assert cap.params == {}


def test_get_conversation_404_none():
    c = _make_client(lambda r: httpx.Response(404))
    assert asyncio.run(c.get_conversation(_U, _INV)) is None


# ── persona dialog (누적) ─────────────────────────────────────────────────────


def test_get_persona_dialog_found():
    cap = _Capture()
    c = _make_client(lambda r: _ok({"turns": []}), cap)
    out = asyncio.run(c.get_persona_dialog(_U, _INV, 1, "buddy"))
    assert out == {"turns": []}
    assert cap.method == "GET"
    assert cap.path == f"/sessions/{_U}/{_INV}/runtime/01.buddy/dialog/buddy"


def test_get_persona_dialog_404_none():
    c = _make_client(lambda r: httpx.Response(404))
    assert asyncio.run(c.get_persona_dialog(_U, _INV, 2, "missing")) is None


def test_get_persona_dialog_other_error_raises():
    c = _make_client(lambda r: httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(c.get_persona_dialog(_U, _INV, 1, "buddy"))


def test_patch_persona_dialog_sends_add_ops():
    cap = _Capture()
    c = _make_client(lambda r: _ok({"updated": True}), cap)
    out = asyncio.run(c.patch_persona_dialog(_U, _INV, 2, "analysis", {"summary": "s", "count": 3}))
    assert out == {"updated": True}
    assert cap.method == "PATCH"
    assert cap.path == f"/sessions/{_U}/{_INV}/runtime/02.director/dialog/analysis"
    assert cap.json_body == [
        {"op": "add", "path": "/summary", "value": "s"},
        {"op": "add", "path": "/count", "value": 3},
    ]


def test_patch_persona_dialog_raises():
    c = _make_client(lambda r: httpx.Response(422))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(c.patch_persona_dialog(_U, _INV, 2, "analysis", {"x": 1}))


# ── _get_or_none / _model_get (간접: wrappers) ────────────────────────────────
# (위 dialog/turn/conversation 테스트가 _get_or_none / _model_get 전 분기 커버)


# ── invention object model ────────────────────────────────────────────────────


def test_get_iom_root_no_pointer():
    cap = _Capture()
    c = _make_client(lambda r: _ok({"root": 1}), cap)
    out = asyncio.run(c.get_invention_object_model(_U, _INV))
    assert out == {"root": 1}
    assert cap.method == "GET"
    assert cap.path == f"/sessions/{_U}/{_INV}/models/invention-object-model"
    assert cap.params == {}


def test_get_iom_with_pointer():
    cap = _Capture()
    c = _make_client(lambda r: _ok({"sub": True}), cap)
    out = asyncio.run(c.get_invention_object_model(_U, _INV, pointer="/claims/0"))
    assert out == {"sub": True}
    assert cap.params == {"pointer": "/claims/0"}


def test_get_iom_404_none():
    c = _make_client(lambda r: httpx.Response(404))
    assert asyncio.run(c.get_invention_object_model(_U, _INV)) is None


def test_get_iom_other_error_raises():
    c = _make_client(lambda r: httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(c.get_invention_object_model(_U, _INV))


# ── drawing manifest / part ───────────────────────────────────────────────────


def test_get_drawing_manifest_found():
    cap = _Capture()
    c = _make_client(lambda r: _ok({"drawings": []}), cap)
    out = asyncio.run(c.get_drawing_manifest(_U, _INV))
    assert out == {"drawings": []}
    assert cap.path == f"/sessions/{_U}/{_INV}/drawings/manifest"


def test_get_drawing_manifest_404_none():
    c = _make_client(lambda r: httpx.Response(404))
    assert asyncio.run(c.get_drawing_manifest(_U, _INV)) is None


def test_get_drawing_part_found():
    cap = _Capture()
    c = _make_client(lambda r: _ok({"items": []}), cap)
    out = asyncio.run(c.get_drawing_part(_U, _INV, "d1", "numerals"))
    assert out == {"items": []}
    assert cap.method == "GET"
    assert cap.path == f"/sessions/{_U}/{_INV}/drawings/d1/numerals"


def test_get_drawing_part_404_none():
    c = _make_client(lambda r: httpx.Response(404))
    assert asyncio.run(c.get_drawing_part(_U, _INV, "d1", "dl")) is None


def test_get_drawing_part_bad_part_raises_valueerror():
    c = _make_client(lambda r: _ok({}))
    with pytest.raises(ValueError, match="unknown drawing part"):
        asyncio.run(c.get_drawing_part(_U, _INV, "d1", "bogus"))


def test_put_drawing_part():
    cap = _Capture()
    c = _make_client(lambda r: _ok({}), cap)
    body = {"figure": "data"}
    out = asyncio.run(c.put_drawing_part(_U, _INV, "d1", "figure", body))
    assert out is None
    assert cap.method == "PUT"
    assert cap.path == f"/sessions/{_U}/{_INV}/drawings/d1/figure"
    assert cap.json_body == body


def test_put_drawing_part_bad_part_raises_valueerror():
    c = _make_client(lambda r: _ok({}))
    with pytest.raises(ValueError, match="unknown drawing part"):
        asyncio.run(c.put_drawing_part(_U, _INV, "d1", "bogus", {}))


def test_put_drawing_part_raises():
    c = _make_client(lambda r: httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(c.put_drawing_part(_U, _INV, "d1", "numerals", {}))


# ── CDS / CMM / UR ─────────────────────────────────────────────────────────────


def test_put_concept_discovery_stack():
    cap = _Capture()
    c = _make_client(lambda r: _ok({}), cap)
    body = {"fields": {"problem": "p"}}
    out = asyncio.run(c.put_concept_discovery_stack(_U, _INV, body))
    assert out is None
    assert cap.method == "PUT"
    assert cap.path == f"/sessions/{_U}/{_INV}/models/concept-discovery-stack"
    assert cap.json_body == body


def test_put_concept_discovery_stack_raises():
    c = _make_client(lambda r: httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(c.put_concept_discovery_stack(_U, _INV, {}))


def test_get_concept_discovery_stack():
    cap = _Capture()
    c = _make_client(lambda r: _ok({"fields": {}}), cap)
    out = asyncio.run(c.get_concept_discovery_stack(_U, _INV))
    assert out == {"fields": {}}
    assert cap.path == f"/sessions/{_U}/{_INV}/models/concept-discovery-stack"


def test_get_concept_maturity_model_with_pointer():
    cap = _Capture()
    c = _make_client(lambda r: _ok({"overall": 0.5}), cap)
    out = asyncio.run(c.get_concept_maturity_model(_U, _INV, pointer="/overall"))
    assert out == {"overall": 0.5}
    assert cap.path == f"/sessions/{_U}/{_INV}/models/concept-maturity-model"
    assert cap.params == {"pointer": "/overall"}


def test_put_concept_maturity_model():
    cap = _Capture()
    c = _make_client(lambda r: _ok({}), cap)
    body = {"overall": 0.7, "clarity": 0.8}
    out = asyncio.run(c.put_concept_maturity_model(_U, _INV, body))
    assert out is None
    assert cap.method == "PUT"
    assert cap.path == f"/sessions/{_U}/{_INV}/models/concept-maturity-model"
    assert cap.json_body == body


def test_put_concept_maturity_model_raises():
    c = _make_client(lambda r: httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(c.put_concept_maturity_model(_U, _INV, {}))


def test_put_user_roadmap_array_body():
    cap = _Capture()
    c = _make_client(lambda r: _ok({}), cap)
    body = [{"id": "r1", "title": "T"}]
    out = asyncio.run(c.put_user_roadmap(_U, _INV, body))
    assert out is None
    assert cap.method == "PUT"
    assert cap.path == f"/sessions/{_U}/{_INV}/models/user-roadmap"
    assert cap.json_body == body


def test_put_user_roadmap_raises():
    c = _make_client(lambda r: httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(c.put_user_roadmap(_U, _INV, []))


def test_get_user_roadmap_array():
    cap = _Capture()
    c = _make_client(lambda r: _ok([{"id": "r1"}]), cap)
    out = asyncio.run(c.get_user_roadmap(_U, _INV))
    assert out == [{"id": "r1"}]
    assert cap.path == f"/sessions/{_U}/{_INV}/models/user-roadmap"


def test_get_user_roadmap_404_none():
    c = _make_client(lambda r: httpx.Response(404))
    assert asyncio.run(c.get_user_roadmap(_U, _INV)) is None


# ── step output (trail → rt → output) ─────────────────────────────────────────


def _trail_then_rt(trail_lines: str, rt_payload: dict[str, Any]):
    """첫 GET(trail) 는 jsonl text, 둘째 GET(rt) 는 rt json 을 돌려주는 handler."""
    state = {"n": 0}

    def _h(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/trail"):
            return httpx.Response(200, text=trail_lines)
        state["n"] += 1
        return httpx.Response(200, json=rt_payload)

    return _h


def test_get_step_output_structured():
    lines = (
        '{"event":"rt_enqueued","step_id":"s0","rt_id":"rtA"}\n'
        '{"event":"rt_started","step_id":"s0","rt_id":"rtA"}\n'
    )
    rt = {"rt_id": "rtA", "output": {"structured": {"answer": 42}}}
    c = _make_client(_trail_then_rt(lines, rt))
    out = asyncio.run(c.get_step_output(_U, _INV, 2, "ch1", "s0"))
    assert out == {"answer": 42}


def test_get_step_output_falls_back_to_text():
    lines = '{"event":"rt_started","step_id":"s1","rt_id":"rtB"}\n'
    rt = {"rt_id": "rtB", "output": {"text": "plain"}}
    c = _make_client(_trail_then_rt(lines, rt))
    out = asyncio.run(c.get_step_output(_U, _INV, 2, "ch1", "s1"))
    assert out == {"text": "plain"}


def test_get_step_output_no_output_text_defaults_empty():
    lines = '{"event":"rt_started","step_id":"s1","rt_id":"rtB"}\n'
    rt = {"rt_id": "rtB"}  # output 없음 → {} → text default ""
    c = _make_client(_trail_then_rt(lines, rt))
    out = asyncio.run(c.get_step_output(_U, _INV, 2, "ch1", "s1"))
    assert out == {"text": ""}


def test_get_step_output_step_not_in_trail_returns_none():
    lines = '{"event":"rt_started","step_id":"other","rt_id":"rtZ"}\n'
    c = _make_client(_trail_then_rt(lines, {"rt_id": "rtZ"}))
    out = asyncio.run(c.get_step_output(_U, _INV, 2, "ch1", "s0"))
    assert out is None


def test_get_step_output_empty_trail_returns_none():
    c = _make_client(lambda r: httpx.Response(404))  # trail 404 → []
    out = asyncio.run(c.get_step_output(_U, _INV, 2, "ch1", "s0"))
    assert out is None


# ── outputs list ───────────────────────────────────────────────────────────────


def test_get_outputs_list_found():
    cap = _Capture()
    c = _make_client(lambda r: _ok({"files": ["draft.docx"]}), cap)
    out = asyncio.run(c.get_outputs_list(_U, _INV))
    assert out == {"files": ["draft.docx"]}
    assert cap.method == "GET"
    assert cap.path == f"/sessions/{_U}/{_INV}/outputs"


def test_get_outputs_list_404_none():
    c = _make_client(lambda r: httpx.Response(404))
    assert asyncio.run(c.get_outputs_list(_U, _INV)) is None


def test_get_documents_list_alias_is_get_outputs_list():
    assert CMClient.get_documents_list is CMClient.get_outputs_list


# ── load_resource (resource_key dispatch) ─────────────────────────────────────


def test_load_resource_iom():
    cap = _Capture()
    c = _make_client(lambda r: _ok({"iom": True}), cap)
    out = asyncio.run(c.load_resource(_U, _INV, "invention_object_model"))
    assert out == {"iom": True}
    assert cap.path == f"/sessions/{_U}/{_INV}/models/invention-object-model"


def test_load_resource_drawing_manifest():
    cap = _Capture()
    c = _make_client(lambda r: _ok({"drawings": []}), cap)
    out = asyncio.run(c.load_resource(_U, _INV, "drawing_manifest"))
    assert out == {"drawings": []}
    assert cap.path == f"/sessions/{_U}/{_INV}/drawings/manifest"


def test_load_resource_conversation():
    cap = _Capture()
    c = _make_client(lambda r: _ok({"messages": []}), cap)
    out = asyncio.run(c.load_resource(_U, _INV, "conversation"))
    assert out == {"messages": []}
    assert cap.path == f"/sessions/{_U}/{_INV}/runtime/00.dro/conversation"


def test_load_resource_dialog():
    cap = _Capture()
    c = _make_client(lambda r: _ok({"turns": []}), cap)
    out = asyncio.run(c.load_resource(_U, _INV, "dialog.2.analysis"))
    assert out == {"turns": []}
    assert cap.path == f"/sessions/{_U}/{_INV}/runtime/02.director/dialog/analysis"


def test_load_resource_dialog_bad_shape_raises():
    c = _make_client(lambda r: _ok({}))
    with pytest.raises(ValueError, match="dialog resource must be"):
        asyncio.run(c.load_resource(_U, _INV, "dialog.2"))


def test_load_resource_drawing_part():
    cap = _Capture()
    c = _make_client(lambda r: _ok({"items": []}), cap)
    out = asyncio.run(c.load_resource(_U, _INV, "drawing.d1.figure"))
    assert out == {"items": []}
    assert cap.path == f"/sessions/{_U}/{_INV}/drawings/d1/figure"


def test_load_resource_drawing_bad_shape_raises():
    c = _make_client(lambda r: _ok({}))
    with pytest.raises(ValueError, match="drawing resource must be"):
        asyncio.run(c.load_resource(_U, _INV, "drawing.d1"))


def test_load_resource_unknown_raises():
    c = _make_client(lambda r: _ok({}))
    with pytest.raises(ValueError, match="unknown CM resource_key"):
        asyncio.run(c.load_resource(_U, _INV, "nope"))
