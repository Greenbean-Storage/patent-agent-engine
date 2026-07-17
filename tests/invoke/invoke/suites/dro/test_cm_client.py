"""200.DRO cm_client — CM HTTP wrapper 전수 (invoke 단위).

대상: 200.DRO/src/cm_client.py (CMClient 고유부 + get_cm_client. 공통 base/dict_to_add_ops 는
venezia_cm_client — shared suite 가 테스트).
전략: httpx.MockTransport(handler) 를 CMClient._client 에 주입 — handler 가 method+url 로
canned 응답을 돌려준다. 각 wrapper 메서드가 (1) 올바른 method+url(+body/params) 로 호출하고
(2) 응답을 올바르게 반환·파싱하며 (3) 404→None / raise_for_status 분기를 타는지 진짜 assert.

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
sys.path.insert(0, str(ROOT / "200.DRO"))

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


def _make_client(
    handler,
    capture: _Capture | None = None,
) -> CMClient:
    """MockTransport 주입된 CMClient. handler(request)->Response. capture 시 요청 기록."""
    cap = capture or _Capture()

    def _wrapped(request: httpx.Request) -> httpx.Response:
        cap.method = request.method
        cap.path = request.url.path
        cap.params = dict(request.url.params)
        cap.raw = request.content
        try:
            cap.json_body = httpx.Response(200, content=request.content).json()
        except Exception:  # noqa: BLE001 — non-JSON (multipart) 요청
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


# (dict_to_add_ops 는 venezia_cm_client 로 이동 — shared suite test_cm_client_base.py 가 테스트)


# ── 생성자 / aclose / get_cm_client ───────────────────────────────────────────


def test_init_strips_trailing_slash_and_timeout():
    c = CMClient(base_url="http://cm:1/", timeout=12.5)
    assert c.base == "http://cm:1"
    assert c.timeout == 12.5


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


# ── persona dialog ──────────────────────────────────────────────────────────────


def test_get_persona_dialog_found():
    cap = _Capture()
    c = _make_client(lambda r: _ok({"turns": []}), cap)
    out = asyncio.run(c.get_persona_dialog(_U, _INV, 1, "buddy"))
    assert out == {"turns": []}
    assert cap.method == "GET"
    assert cap.path == f"/sessions/{_U}/{_INV}/runtime/01.buddy/dialog/buddy"


def test_get_persona_dialog_404_returns_none():
    c = _make_client(lambda r: httpx.Response(404))
    out = asyncio.run(c.get_persona_dialog(_U, _INV, 2, "missing"))
    assert out is None


def test_get_persona_dialog_other_error_raises():
    c = _make_client(lambda r: httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(c.get_persona_dialog(_U, _INV, 1, "buddy"))


# ── DRC chain ─────────────────────────────────────────────────────────────────


def test_create_chain():
    cap = _Capture()
    c = _make_client(lambda r: _ok({"chain_id": "ch1"}), cap)
    trigger = {"kind": "message"}
    out = asyncio.run(c.create_chain(_U, _INV, "ch1", "P02.R00.X", 2, trigger))
    assert out == {"chain_id": "ch1"}
    assert cap.method == "POST"
    assert cap.path == f"/sessions/{_U}/{_INV}/runtime"
    assert cap.json_body == {
        "chain_id": "ch1",
        "pipeline_id": "P02.R00.X",
        "persona": 2,
        "trigger": trigger,
    }


def test_get_chain():
    cap = _Capture()
    c = _make_client(lambda r: _ok({"manifest": True}), cap)
    out = asyncio.run(c.get_chain(_U, _INV, 3, "ch9"))
    assert out == {"manifest": True}
    assert cap.method == "GET"
    assert cap.path == f"/sessions/{_U}/{_INV}/runtime/03.finder/ch9"


def test_patch_chain_sends_add_ops():
    cap = _Capture()
    c = _make_client(lambda r: _ok({"status": "done"}), cap)
    out = asyncio.run(c.patch_chain(_U, _INV, 2, "ch1", {"status": "done"}))
    assert out == {"status": "done"}
    assert cap.method == "PATCH"
    assert cap.path == f"/sessions/{_U}/{_INV}/runtime/02.director/ch1"
    assert cap.json_body == [{"op": "add", "path": "/status", "value": "done"}]


def test_append_trail():
    cap = _Capture()
    c = _make_client(lambda r: _ok({}), cap)
    event = {"type": "rt_started", "rt_id": "rt1"}
    out = asyncio.run(c.append_trail(_U, _INV, 4, "ch2", event))
    assert out is None
    assert cap.method == "POST"
    assert cap.path == f"/sessions/{_U}/{_INV}/runtime/04.thinker/ch2/trail"
    assert cap.json_body == event


def test_append_trail_raises():
    c = _make_client(lambda r: httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(c.append_trail(_U, _INV, 4, "ch2", {"e": 1}))


# ── RT ──────────────────────────────────────────────────────────────────────────


def test_create_rt():
    cap = _Capture()
    c = _make_client(lambda r: _ok({"rt_id": "rt1"}), cap)
    rt = {"step_id": "s0", "kind": "llm"}
    out = asyncio.run(c.create_rt(_U, _INV, 5, "ch3", rt))
    assert out == {"rt_id": "rt1"}
    assert cap.method == "POST"
    assert cap.path == f"/sessions/{_U}/{_INV}/runtime/05.crafter/ch3/rts"
    assert cap.json_body == rt


def test_get_rt():
    cap = _Capture()
    c = _make_client(lambda r: _ok({"rt_id": "rt7", "status": "pending"}), cap)
    out = asyncio.run(c.get_rt(_U, _INV, 6, "ch4", "rt7"))
    assert out == {"rt_id": "rt7", "status": "pending"}
    assert cap.method == "GET"
    assert cap.path == f"/sessions/{_U}/{_INV}/runtime/06.inspector/ch4/rts/rt7"


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


def test_get_rt_raises():
    c = _make_client(lambda r: httpx.Response(404))
    # get_rt has no 404→None branch: 404 must raise.
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(c.get_rt(_U, _INV, 1, "ch5", "rtX"))


# ── persona queue ────────────────────────────────────────────────────────────────


def test_persona_queue_push():
    cap = _Capture()
    c = _make_client(lambda r: _ok({"queued": True}), cap)
    out = asyncio.run(c.persona_queue_push(_U, _INV, 2, "rt1", "ch1"))
    assert out == {"queued": True}
    assert cap.method == "POST"
    assert cap.path == f"/sessions/{_U}/{_INV}/runtime/02.director/queue/push"
    assert cap.json_body == {"rt_id": "rt1", "chain_id": "ch1"}


def test_persona_queue_pop():
    cap = _Capture()
    c = _make_client(lambda r: _ok({"rt_id": "rt1", "chain_id": "ch1"}), cap)
    out = asyncio.run(c.persona_queue_pop(_U, _INV, 3))
    assert out == {"rt_id": "rt1", "chain_id": "ch1"}
    assert cap.method == "POST"
    assert cap.path == f"/sessions/{_U}/{_INV}/runtime/03.finder/queue/pop"


def test_persona_queue_pop_with_chain_and_ttl():
    """chain-scoped + lease ttl — body 에 둘 다 전달 (D-1)."""
    cap = _Capture()
    c = _make_client(lambda r: _ok({"rt_id": "rt1", "chain_id": "ch1"}), cap)
    asyncio.run(c.persona_queue_pop(_U, _INV, 3, chain_id="ch1", lease_ttl_s=2400.0))
    assert cap.json_body == {"chain_id": "ch1", "lease_ttl_s": 2400.0}


def test_persona_queue_release():
    """본인 rt_id lease 해제 (구 clear_inflight 폐기 — rt_id 별 lease)."""
    cap = _Capture()
    c = _make_client(lambda r: _ok({"leases": {}}), cap)
    out = asyncio.run(c.persona_queue_release(_U, _INV, 6, "rt-9"))
    assert out == {"leases": {}}
    assert cap.method == "POST"
    assert cap.path == f"/sessions/{_U}/{_INV}/runtime/06.inspector/queue/release"
    assert cap.json_body == {"rt_id": "rt-9"}


def test_get_persona_queue():
    """worker 가 다음 구동 chain 선택용 — 순수 GET (lease 안 잡음, pop 과 별개)."""
    cap = _Capture()
    c = _make_client(lambda r: _ok({"pending": [{"chain_id": "ch1"}], "leases": {}}), cap)
    out = asyncio.run(c.get_persona_queue(_U, _INV, 3))
    assert out == {"pending": [{"chain_id": "ch1"}], "leases": {}}
    assert cap.method == "GET"
    assert cap.path == f"/sessions/{_U}/{_INV}/runtime/03.finder/queue"


def test_get_persona_queue_404_empty():
    """큐 파일 미생성(404) → 빈 큐 default (fail-loud 아님 — idle worker 정상 경로)."""
    c = _make_client(lambda r: httpx.Response(404))
    out = asyncio.run(c.get_persona_queue(_U, _INV, 2))
    assert out == {"pending": [], "leases": {}}


# ── A-3 재시작 복구 (list_active_chains · get_trail) ─────────────────────────────


def test_list_active_chains():
    """전 세션 미완 chain 열거 — DRO 재시작 자동복구 진입점."""
    cap = _Capture()
    chains = [{"user_id": "u", "work_id": "i", "persona": 2, "chain_id": "c1"}]
    c = _make_client(lambda r: _ok({"chains": chains}), cap)
    out = asyncio.run(c.list_active_chains())
    assert out == chains
    assert cap.method == "GET"
    assert cap.path == "/admin/active-chains"


def test_list_active_chains_missing_key_empty():
    c = _make_client(lambda r: _ok({}))
    assert asyncio.run(c.list_active_chains()) == []


def test_get_trail_parses_ndjson_skips_broken():
    """trail ndjson → event list, 깨진 줄/빈 줄 건너뜀 (재시작 재구성용)."""
    cap = _Capture()
    body = (
        '{"event":"rt_enqueued","step_id":"s0","rt_id":"r0"}\n'
        "\n"
        "not json\n"
        '{"event":"rt_completed","rt_id":"r0"}\n'
    )
    c = _make_client(lambda r: httpx.Response(200, content=body), cap)
    out = asyncio.run(c.get_trail(_U, _INV, 2, "c1"))
    assert out == [
        {"event": "rt_enqueued", "step_id": "s0", "rt_id": "r0"},
        {"event": "rt_completed", "rt_id": "r0"},
    ]
    assert cap.method == "GET"
    assert cap.path == f"/sessions/{_U}/{_INV}/runtime/02.director/c1/trail"


def test_get_trail_404_empty():
    c = _make_client(lambda r: httpx.Response(404))
    assert asyncio.run(c.get_trail(_U, _INV, 2, "c1")) == []


def test_get_chains():
    """이 work 의 chain 인덱스 read — admission dedup 판정용 (D-1, C3)."""
    cap = _Capture()
    chains = [{"chain_id": "c1", "persona": 2, "pipeline_id": "P02.R00.X", "status": "pending"}]
    c = _make_client(lambda r: _ok({"chains": chains}), cap)
    out = asyncio.run(c.get_chains(_U, _INV))
    assert out == chains
    assert cap.method == "GET"
    assert cap.path == f"/sessions/{_U}/{_INV}/runtime"


def test_get_chains_missing_key_empty():
    c = _make_client(lambda r: _ok({}))
    assert asyncio.run(c.get_chains(_U, _INV)) == []


# ── model GET (_model_get + wrappers) ───────────────────────────────────────────


def test_model_get_root_no_pointer():
    cap = _Capture()
    c = _make_client(lambda r: _ok({"root": 1}), cap)
    out = asyncio.run(c.get_iom(_U, _INV))
    assert out == {"root": 1}
    assert cap.method == "GET"
    assert cap.path == f"/sessions/{_U}/{_INV}/models/invention-object-model"
    assert cap.params == {}  # pointer="" → no params


def test_model_get_with_pointer_sets_query():
    cap = _Capture()
    c = _make_client(lambda r: _ok({"sub": True}), cap)
    out = asyncio.run(c.get_iom(_U, _INV, pointer="/claims/0"))
    assert out == {"sub": True}
    assert cap.params == {"pointer": "/claims/0"}


def test_model_get_404_returns_none():
    c = _make_client(lambda r: httpx.Response(404))
    assert asyncio.run(c.get_iom(_U, _INV)) is None


def test_model_get_other_error_raises():
    c = _make_client(lambda r: httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(c.get_iom(_U, _INV))


def test_get_concept_discovery_stack():
    cap = _Capture()
    c = _make_client(lambda r: _ok({"fields": {}}), cap)
    out = asyncio.run(c.get_concept_discovery_stack(_U, _INV))
    assert out == {"fields": {}}
    assert cap.path == f"/sessions/{_U}/{_INV}/models/concept-discovery-stack"


def test_get_concept_maturity_model():
    cap = _Capture()
    c = _make_client(lambda r: _ok({"overall": 0.5}), cap)
    out = asyncio.run(c.get_concept_maturity_model(_U, _INV, pointer="/overall"))
    assert out == {"overall": 0.5}
    assert cap.path == f"/sessions/{_U}/{_INV}/models/concept-maturity-model"
    assert cap.params == {"pointer": "/overall"}


def test_get_user_roadmap_array():
    cap = _Capture()
    c = _make_client(lambda r: _ok([{"id": "r1"}]), cap)
    out = asyncio.run(c.get_user_roadmap(_U, _INV))
    assert out == [{"id": "r1"}]
    assert cap.path == f"/sessions/{_U}/{_INV}/models/user-roadmap"


def test_get_user_roadmap_404_none():
    c = _make_client(lambda r: httpx.Response(404))
    assert asyncio.run(c.get_user_roadmap(_U, _INV)) is None


def test_get_conversation():
    cap = _Capture()
    c = _make_client(lambda r: _ok({"messages": []}), cap)
    out = asyncio.run(c.get_conversation(_U, _INV, pointer="/messages"))
    assert out == {"messages": []}
    assert cap.path == f"/sessions/{_U}/{_INV}/runtime/00.dro/conversation"
    assert cap.params == {"pointer": "/messages"}


# ── drawing manifest ────────────────────────────────────────────────────────────


def test_get_drawing_manifest_found():
    cap = _Capture()
    c = _make_client(lambda r: _ok({"drawings": []}), cap)
    out = asyncio.run(c.get_drawing_manifest(_U, _INV))
    assert out == {"drawings": []}
    assert cap.method == "GET"
    assert cap.path == f"/sessions/{_U}/{_INV}/drawings/manifest"


def test_get_drawing_manifest_404_none():
    c = _make_client(lambda r: httpx.Response(404))
    assert asyncio.run(c.get_drawing_manifest(_U, _INV)) is None


def test_get_drawing_manifest_other_error_raises():
    c = _make_client(lambda r: httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(c.get_drawing_manifest(_U, _INV))


# ── documents (outputs) ──────────────────────────────────────────────────────────


def test_upload_document_json_response():
    cap = _Capture()
    c = _make_client(lambda r: _ok({"key": "s3://b/draft.docx", "size": 3}), cap)
    out = asyncio.run(c.upload_document(_U, _INV, "draft.docx", b"abc"))
    assert out == {"key": "s3://b/draft.docx", "size": 3}
    assert cap.method == "PUT"
    assert cap.path == f"/sessions/{_U}/{_INV}/outputs/draft.docx"


def test_upload_document_204_synthesizes_result():
    c = _make_client(lambda r: httpx.Response(204))
    out = asyncio.run(c.upload_document(_U, _INV, "draft.docx", b"abcd"))
    assert out == {"filename": "draft.docx", "size": 4}


def test_upload_document_200_empty_content_synthesizes_result():
    """200 이지만 body 비어있음 → not r.content 분기 → 합성 result."""
    c = _make_client(lambda r: httpx.Response(200, content=b""))
    out = asyncio.run(c.upload_document(_U, _INV, "x.docx", b"ab"))
    assert out == {"filename": "x.docx", "size": 2}


def test_upload_document_non_json_content_returns_empty_dict():
    """200 + 비어있지 않은 body 인데 content-type 이 json 아님 → {}."""
    c = _make_client(
        lambda r: httpx.Response(200, content=b"PLAINTEXT", headers={"content-type": "text/plain"})
    )
    out = asyncio.run(c.upload_document(_U, _INV, "x.docx", b"ab"))
    assert out == {}


def test_upload_document_raises():
    c = _make_client(lambda r: httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(c.upload_document(_U, _INV, "x.docx", b"ab"))


def test_download_document_found():
    cap = _Capture()
    c = _make_client(lambda r: httpx.Response(200, content=b"DOCXBYTES"), cap)
    out = asyncio.run(c.download_document(_U, _INV, "draft.docx"))
    assert out == b"DOCXBYTES"
    assert cap.method == "GET"
    assert cap.path == f"/sessions/{_U}/{_INV}/outputs/draft.docx"


def test_download_document_404_none():
    c = _make_client(lambda r: httpx.Response(404))
    assert asyncio.run(c.download_document(_U, _INV, "missing.docx")) is None


def test_download_document_other_error_raises():
    c = _make_client(lambda r: httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(c.download_document(_U, _INV, "draft.docx"))
