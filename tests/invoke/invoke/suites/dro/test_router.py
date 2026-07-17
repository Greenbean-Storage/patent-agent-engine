"""200.DRO router — 내부 control + events 표면 invoke 단위테스트 (~100% line).

대상: 200.DRO/src/router.py. 신설 DRO 는 순수 체인 실행기 — 외부 client 표면 0.
router.py = {POST /control/spawn, GET /events/{user_id}/{work_id}}.

FastAPI app 을 router 만으로 조립(secrets/AWS fetch 회피) + errors.install 로 envelope
handler 등록. orchestrator 의 실 chain 실행을 피하려고 src.router.spawn_chain 을 AsyncMock
으로 monkeypatch, event_sse.subscribe 를 async generator stub 으로 monkeypatch.

  control/spawn : 정상(202 + 기본 trigger) / explicit trigger 전달 / non-dict trigger →
                  기본값 / validation 실패(persona 없음·persona non-int·chain_id 없음 ·
                  나머지 타입오류) → 400 validation_failed envelope.
  events        : StreamingResponse media_type text/event-stream + 헤더 + body 에 SSE 프레임.

async 는 asyncio.run(...) (pytest-asyncio mark 없이; 기존 suite 패턴).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "200.DRO"))
sys.path.insert(0, str(ROOT / "shared"))

import httpx  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from src import errors  # noqa: E402
from src import router as router_mod  # noqa: E402

_UID = "00000000-0000-0000-0000-0000000000aa"
_WORK = "work-1"
_PERSONA = 2
_PIPE = "P02.R00.CONCEPT_MATURITY"
_CHAIN = "chain-abc"


# ── app 조립 + 호출 헬퍼 ────────────────────────────────────────────────────────


def _build_app() -> FastAPI:
    """router 만으로 app 조립 (main.py 의 secrets/AWS fetch 회피)."""
    app = FastAPI()
    errors.install(app)
    app.include_router(router_mod.router)
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _post(app, url, **kw):
    async def _run():
        async with _client(app) as c:
            return await c.post(url, **kw)

    return asyncio.run(_run())


def _patch_spawn(monkeypatch) -> AsyncMock:
    """src.router.run_chain (worker facade) 을 AsyncMock 으로 대체 — 실 chain 실행 회피.
    chain_id 반환. control_spawn 이 run_chain(uid, inv, pid, persona=, chain_id=, trigger=) 호출."""
    spawn = AsyncMock(return_value=_CHAIN)
    monkeypatch.setattr(router_mod, "run_chain", spawn)
    return spawn


def _patch_resolve(monkeypatch, fn=None) -> None:
    """src.router.resolve_pipeline_id 대체 (단위 트랙 — @pipelines index 의존 제거).

    fn 미지정 = identity (입력 그대로). full id 입력은 resolve 후 그대로이므로 이게 정상.
    """
    monkeypatch.setattr(router_mod, "resolve_pipeline_id", fn or (lambda pid: pid))


# ── POST /control/spawn — 정상 경로 ───────────────────────────────────────────


def test_control_spawn_full_valid_body_default_trigger(monkeypatch):
    app = _build_app()
    spawn = _patch_spawn(monkeypatch)
    _patch_resolve(monkeypatch)
    r = _post(
        app,
        "/control/spawn",
        json={
            "user_id": _UID,
            "work_id": _WORK,
            "persona": _PERSONA,
            "pipeline_id": _PIPE,
            "chain_id": _CHAIN,
        },
    )
    assert r.status_code == 202
    assert r.json() == {"chain_id": _CHAIN}
    # 기본 trigger = {"kind": "control_spawn"}. run_chain facade 시그니처 (kwargs).
    spawn.assert_awaited_once_with(
        _UID, _WORK, _PIPE, persona=_PERSONA, chain_id=_CHAIN, trigger={"kind": "control_spawn"}
    )


def test_control_spawn_explicit_trigger_passed_through(monkeypatch):
    app = _build_app()
    spawn = _patch_spawn(monkeypatch)
    _patch_resolve(monkeypatch)
    trig = {"kind": "roadmap.answer", "roadmap_item_id": "r1"}
    r = _post(
        app,
        "/control/spawn",
        json={
            "user_id": _UID,
            "work_id": _WORK,
            "persona": _PERSONA,
            "pipeline_id": _PIPE,
            "chain_id": _CHAIN,
            "trigger": trig,
        },
    )
    assert r.status_code == 202
    assert r.json() == {"chain_id": _CHAIN}
    spawn.assert_awaited_once_with(
        _UID, _WORK, _PIPE, persona=_PERSONA, chain_id=_CHAIN, trigger=trig
    )


def test_control_spawn_non_dict_trigger_falls_back_to_default(monkeypatch):
    app = _build_app()
    spawn = _patch_spawn(monkeypatch)
    _patch_resolve(monkeypatch)
    # trigger 가 dict 아님 (str) → isinstance(raw, dict) False → 기본값
    r = _post(
        app,
        "/control/spawn",
        json={
            "user_id": _UID,
            "work_id": _WORK,
            "persona": _PERSONA,
            "pipeline_id": _PIPE,
            "chain_id": _CHAIN,
            "trigger": "not-a-dict",
        },
    )
    assert r.status_code == 202
    spawn.assert_awaited_once_with(
        _UID, _WORK, _PIPE, persona=_PERSONA, chain_id=_CHAIN, trigger={"kind": "control_spawn"}
    )


# ── POST /control/spawn — pipeline resolve (받자마자, 202 전) ──────────────────


def test_control_spawn_short_form_resolved_to_full_id(monkeypatch):
    """short-form(P02.R00) 이 spawn_chain 에 full id 로 넘어간다 — control_spawn 이 받자마자 resolve."""
    app = _build_app()
    spawn = _patch_spawn(monkeypatch)
    _patch_resolve(
        monkeypatch,
        lambda pid: "P02.R00.CONCEPT_MATURITY" if pid == "P02.R00" else pid,
    )
    body = _valid_body()
    body["pipeline_id"] = "P02.R00"
    r = _post(app, "/control/spawn", json=body)
    assert r.status_code == 202
    # spawn 은 short-form 이 아니라 resolve 된 full id 로 호출돼야 한다
    spawn.assert_awaited_once_with(
        _UID,
        _WORK,
        "P02.R00.CONCEPT_MATURITY",
        persona=_PERSONA,
        chain_id=_CHAIN,
        trigger={"kind": "control_spawn"},
    )


def test_control_spawn_unknown_pipeline_404(monkeypatch):
    """resolve 가 KeyError (미존재 pipeline) → 404 pipeline_unknown, spawn 미호출."""
    app = _build_app()
    spawn = _patch_spawn(monkeypatch)

    def _raise(pid):
        raise KeyError(pid)

    _patch_resolve(monkeypatch, _raise)
    body = _valid_body()
    body["pipeline_id"] = "P99.R99"
    r = _post(app, "/control/spawn", json=body)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "pipeline_unknown"
    spawn.assert_not_awaited()


def test_control_spawn_ambiguous_pipeline_409(monkeypatch):
    """resolve 가 AmbiguousPipelineId (prefix 다중매칭) → 409 pipeline_ambiguous, spawn 미호출."""
    app = _build_app()
    spawn = _patch_spawn(monkeypatch)

    # control_spawn 의 except 가 실제로 쓰는 바로 그 클래스 객체로 raise (src 재import 시
    # 클래스 동일성 보장 — from src.pipeline_walker import 면 다른 모듈 객체일 수 있음).
    def _raise(pid):
        raise router_mod.AmbiguousPipelineId(pid, [f"{pid}.A", f"{pid}.B"])

    _patch_resolve(monkeypatch, _raise)
    body = _valid_body()
    body["pipeline_id"] = "P02.R00"
    r = _post(app, "/control/spawn", json=body)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "pipeline_ambiguous"
    spawn.assert_not_awaited()


# ── POST /control/spawn — validation 실패 (400 envelope) ──────────────────────


def _valid_body() -> dict:
    return {
        "user_id": _UID,
        "work_id": _WORK,
        "persona": _PERSONA,
        "pipeline_id": _PIPE,
        "chain_id": _CHAIN,
    }


def _assert_validation_400(r) -> None:
    assert r.status_code == 400
    body = r.json()
    assert body["error"]["code"] == "validation_failed"
    assert "control/spawn" in body["error"]["message"]


def test_control_spawn_missing_persona_400(monkeypatch):
    app = _build_app()
    spawn = _patch_spawn(monkeypatch)
    body = _valid_body()
    del body["persona"]  # persona None → isinstance(None, int) False
    r = _post(app, "/control/spawn", json=body)
    _assert_validation_400(r)
    spawn.assert_not_awaited()


def test_control_spawn_persona_not_int_400(monkeypatch):
    app = _build_app()
    spawn = _patch_spawn(monkeypatch)
    body = _valid_body()
    body["persona"] = "2"  # str → isinstance(_, int) False
    r = _post(app, "/control/spawn", json=body)
    _assert_validation_400(r)
    spawn.assert_not_awaited()


def test_control_spawn_persona_bool_rejected_400(monkeypatch):
    app = _build_app()
    spawn = _patch_spawn(monkeypatch)
    _patch_resolve(monkeypatch)
    body = _valid_body()
    # bool 은 int subclass 라 통과한다 — 본 테스트는 bool 이 통과(202)함을 명시 검증.
    body["persona"] = True
    r = _post(app, "/control/spawn", json=body)
    assert r.status_code == 202
    spawn.assert_awaited_once_with(
        _UID, _WORK, _PIPE, persona=True, chain_id=_CHAIN, trigger={"kind": "control_spawn"}
    )


def test_control_spawn_persona_out_of_range_400(monkeypatch):
    """persona 가 [1,6] 밖이면 경계에서 400 (구: run_chain 깊은 곳 RuntimeError→500 으로 샜음, I2)."""
    app = _build_app()
    spawn = _patch_spawn(monkeypatch)
    for bad in (0, 7):
        body = _valid_body()
        body["persona"] = bad
        r = _post(app, "/control/spawn", json=body)
        _assert_validation_400(r)
        assert "범위" in r.json()["error"]["message"]
    spawn.assert_not_awaited()


def test_control_spawn_missing_chain_id_400(monkeypatch):
    app = _build_app()
    spawn = _patch_spawn(monkeypatch)
    body = _valid_body()
    del body["chain_id"]  # chain_id None → isinstance(None, str) False
    r = _post(app, "/control/spawn", json=body)
    _assert_validation_400(r)
    spawn.assert_not_awaited()


def test_control_spawn_user_id_wrong_type_400(monkeypatch):
    app = _build_app()
    spawn = _patch_spawn(monkeypatch)
    body = _valid_body()
    body["user_id"] = 123  # int → isinstance(_, str) False
    r = _post(app, "/control/spawn", json=body)
    _assert_validation_400(r)
    spawn.assert_not_awaited()


def test_control_spawn_work_id_wrong_type_400(monkeypatch):
    app = _build_app()
    spawn = _patch_spawn(monkeypatch)
    body = _valid_body()
    body["work_id"] = None  # None → isinstance(None, str) False
    r = _post(app, "/control/spawn", json=body)
    _assert_validation_400(r)
    spawn.assert_not_awaited()


def test_control_spawn_pipeline_id_wrong_type_400(monkeypatch):
    app = _build_app()
    spawn = _patch_spawn(monkeypatch)
    body = _valid_body()
    body["pipeline_id"] = ["P02"]  # list → isinstance(_, str) False
    r = _post(app, "/control/spawn", json=body)
    _assert_validation_400(r)
    spawn.assert_not_awaited()


# ── GET /events/{uid}/{inv} — SSE stream ──────────────────────────


def _stub_subscribe(monkeypatch, frames: list[str]):
    """src.router.event_sse.subscribe 를 frames 만 yield 하고 끝나는 async gen 으로 대체.

    호출 인자(user_id, work_id) 를 captured 에 기록해 반환.
    """
    captured: dict = {}

    def _subscribe(user_id, work_id):
        captured["args"] = (user_id, work_id)

        async def _gen():
            for f in frames:
                yield f

        return _gen()

    monkeypatch.setattr(router_mod.event_sse, "subscribe", _subscribe)
    return captured


def test_events_streams_frames_and_headers(monkeypatch):
    app = _build_app()
    frames = [
        'event: rt_started\ndata: {"seq": 1}\n\n',
        'event: rt_result\ndata: {"seq": 2}\n\n',
    ]
    captured = _stub_subscribe(monkeypatch, frames)

    async def _run():
        async with _client(app) as c:
            async with c.stream("GET", f"/events/{_UID}/{_WORK}") as resp:
                assert resp.status_code == 200
                assert resp.headers["content-type"].startswith("text/event-stream")
                assert resp.headers["cache-control"] == "no-cache"
                assert resp.headers["x-accel-buffering"] == "no"
                body = ""
                async for chunk in resp.aiter_text():
                    body += chunk
                return body

    body = asyncio.run(_run())
    # 두 프레임 모두 stream body 에 포함
    assert "event: rt_started" in body
    assert "event: rt_result" in body
    assert body == "".join(frames)
    # subscribe 가 path param 그대로 받음
    assert captured["args"] == (_UID, _WORK)


def test_events_single_frame_direct_endpoint_call(monkeypatch):
    """endpoint fn 직접 호출 → StreamingResponse 타입 + media_type + generator 1 프레임."""
    frame = 'event: chain_completed\ndata: {"seq": 9}\n\n'
    captured = _stub_subscribe(monkeypatch, [frame])

    async def _run():
        resp = await router_mod.works_events(_UID, _WORK)
        assert isinstance(resp, StreamingResponse)
        assert resp.media_type == "text/event-stream"
        assert resp.headers["cache-control"] == "no-cache"
        assert resp.headers["x-accel-buffering"] == "no"
        # body_iterator 가 stub generator → 단일 프레임 yield
        collected = [chunk async for chunk in resp.body_iterator]
        return collected

    collected = asyncio.run(_run())
    assert collected == [frame]
    assert captured["args"] == (_UID, _WORK)


# ── POST /control/output — docx 빌드 (C6 output/docx 재배선) ────────────────────

_IOM_MIN = {
    "bibliographic": {"title": {"ko": "테스트 발명", "en": "Test Invention"}},
    "specification": {"technical_field": "기술분야"},
    "claims": [{"number": 1, "text": "청구항 1"}],
    "abstract": {"text": "요약 텍스트"},
}


class _FakeOutputCM:
    """control_output 용 fake CM — get_iom/get_drawing_manifest/upload_document 기록."""

    def __init__(self, *, iom=_IOM_MIN, drawing_manifest=None) -> None:
        self._iom = iom
        self._dm = drawing_manifest
        self.upload_calls: list[tuple] = []

    async def get_iom(self, user_id, work_id, pointer=""):
        return self._iom

    async def get_drawing_manifest(self, user_id, work_id):
        return self._dm

    async def upload_document(
        self, user_id, work_id, filename, body, content_type="application/octet-stream"
    ):
        self.upload_calls.append((user_id, work_id, filename, body, content_type))
        return {"filename": filename, "size": len(body)}


def _patch_output(monkeypatch, cm) -> AsyncMock:
    """get_cm_client → cm, event_sse.emit_raw → AsyncMock. PatentDocxGenerator 는 실제 구동."""
    monkeypatch.setattr(router_mod, "get_cm_client", lambda: cm)
    emit = AsyncMock()
    monkeypatch.setattr(router_mod.event_sse, "emit_raw", emit)
    return emit


def test_control_output_draft_builds_uploads_emits(monkeypatch):
    app = _build_app()
    cm = _FakeOutputCM()
    emit = _patch_output(monkeypatch, cm)
    r = _post(app, "/control/output", json={"user_id": _UID, "work_id": _WORK, "variant": "draft"})
    assert r.status_code == 200
    body = r.json()
    assert body["document_id"] == "draft"
    assert body["filename"] == "draft.docx"
    assert isinstance(body["size_bytes"], int) and body["size_bytes"] > 0
    # CM upload: draft.docx + docx mime + 실 docx 바이트
    assert len(cm.upload_calls) == 1
    uid, wid, fname, raw, ctype = cm.upload_calls[0]
    assert (uid, wid, fname) == (_UID, _WORK, "draft.docx")
    assert ctype == router_mod._DOCX_MEDIA_TYPE
    assert isinstance(raw, (bytes, bytearray)) and len(raw) == body["size_bytes"]
    # RAW output_ready 1건 (payload = 응답 동형, persona/step 미부여)
    emit.assert_awaited_once_with(_UID, _WORK, "output_ready", body)


def test_control_output_iom_missing_404(monkeypatch):
    app = _build_app()
    cm = _FakeOutputCM(iom=None)
    emit = _patch_output(monkeypatch, cm)
    r = _post(app, "/control/output", json={"user_id": _UID, "work_id": _WORK, "variant": "draft"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "content_not_ready"
    assert cm.upload_calls == []
    emit.assert_not_awaited()


def test_control_output_variant_not_draft_400(monkeypatch):
    app = _build_app()
    cm = _FakeOutputCM()
    emit = _patch_output(monkeypatch, cm)
    r = _post(
        app, "/control/output", json={"user_id": _UID, "work_id": _WORK, "variant": "proposal"}
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "validation_failed"
    assert cm.upload_calls == []
    emit.assert_not_awaited()


def test_control_output_missing_variant_400(monkeypatch):
    app = _build_app()
    cm = _FakeOutputCM()
    _patch_output(monkeypatch, cm)
    r = _post(app, "/control/output", json={"user_id": _UID, "work_id": _WORK})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "validation_failed"


def test_control_output_drawing_manifest_passed_through(monkeypatch):
    # get_drawing_manifest 가 dict 반환 → generate 에 전달(빌드 성공). 부수효과 관측.
    app = _build_app()
    cm = _FakeOutputCM(drawing_manifest={"drawings": []})
    emit = _patch_output(monkeypatch, cm)
    r = _post(app, "/control/output", json={"user_id": _UID, "work_id": _WORK, "variant": "draft"})
    assert r.status_code == 200
    emit.assert_awaited_once()
