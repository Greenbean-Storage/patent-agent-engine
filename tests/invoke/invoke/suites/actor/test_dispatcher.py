"""300.Actor dispatcher — handle() SSE generator 전수 (invoke 단위).

대상: 300.Actor/src/dispatcher.py
  - _accepts_persona (env 게이트). 동시성 슬롯은 src/slots.py — test_slots.py 가 커버.
  - handle() async generator:
      * persona 는 dispatch body 가 전달 → 그 persona dir 에서 직접 get_rt (3a, 순회 폐기)
      * RT not found (해당 persona dir miss) → error 이벤트
      * persona not handled by this actor → error 이벤트
      * composer-key-missing → RuntimeError → error 이벤트
      * media_refs passthrough (binary 인라인 폐기 — media_refs 만 sess.run/trail 로 전달)
      * loaded_tools (tools.get None warning + 정상)
      * make_fetch_tools / create_llm_session / compose_prompt / cm_fetch closure
      * SSE 이벤트 순서 (started → progress → result)
      * sess.run / put_agent_state / patch_rt 호출 인자

전략: dispatcher 모듈 namespace 의 협력자를 monkeypatch — get_cm_client(AsyncMock CMClient),
create_llm_session(fake session), compose_prompt(cm_fetch closure 를 직접 구동하는 fake),
make_fetch_tools, tools.get. 벤더 SDK 직접 호출 없음. compose_prompt fake 가 dispatcher 의
_cm_fetch closure 를 호출해 모든 resource 분기를 커버. 진짜 assert.

async 는 asyncio.run(...) (pytest-asyncio mark 없이; 기존 suite 패턴).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import httpx  # noqa: F401  (suite 일관 — 미사용이어도 venv 보장)

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "300.Actor"))

from src import dispatcher  # noqa: E402

_U = "user-uuid"
_INV = "inv-uuid"
_CH = "chain-uuid"
_RT = "rt-uuid"


# ── helpers ──────────────────────────────────────────────────────────────────


def _parse_events(chunks: list[str]) -> list[tuple[str, Any]]:
    """SSE 문자열 chunk 들을 (event_name, data_obj) 튜플 list 로 파싱."""
    out: list[tuple[str, Any]] = []
    for chunk in chunks:
        name: str | None = None
        data: Any = None
        for line in chunk.splitlines():
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        assert name is not None
        out.append((name, data))
    return out


async def _drain(gen) -> list[str]:
    return [c async for c in gen]


class _FakeSession:
    """create_llm_session 대체 — sdk/model 메타 + async run + export_state (컨텍스트 ②)."""

    def __init__(self, *, result: dict[str, Any] | None = None, raise_on_run: bool = False) -> None:
        self.sdk = "fake-sdk"
        self.model = "fake-model"
        self._result = result if result is not None else {"text": "ok", "structured": {"a": 1}}
        self._raise = raise_on_run
        self.run_kwargs: dict[str, Any] | None = None
        self._state = {
            "schema_version": 1,
            "vendor": "fixture",
            "model": "fake-model",
            "items": [{"role": "assistant", "content": "ok"}],
        }

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        self.run_kwargs = kwargs
        if self._raise:
            raise ValueError("llm boom")
        return self._result

    def export_state(self) -> dict[str, Any]:
        return dict(self._state)


def _base_rt_input(**over: Any) -> dict[str, Any]:
    """composer 필수 키(inject_context_spec / persona_prompt) 충족 RT.input."""
    inp: dict[str, Any] = {
        "persona_prompt": "you are a tester",
        "inject_context_spec": {},
        "recommended_context_spec": {},
        "fragments": {},
        "instructions": {"inline": "do the thing"},
        "available_tools": [],
        "response_schema": {"required": ["a"]},
        "context": {"steps": {"s0": {"text": "prev"}}},
        "media_refs": [],
    }
    inp.update(over)
    return inp


def _make_cm(
    rt: dict[str, Any] | None,
) -> AsyncMock:
    """AsyncMock CMClient. get_rt 는 (dispatch persona dir 의) rt 반환 (없으면 None)."""
    cm = AsyncMock()

    async def _get_rt(u, i, persona, ch, rt_id):
        return rt

    cm.get_rt.side_effect = _get_rt
    # 컨텍스트 ② — CM 응답 = vendor 원형 envelope (+ CM 스탬프)
    cm.get_agent_state.return_value = {
        "persona": 1,
        "schema_version": 1,
        "vendor": "fixture",
        "model": "fake-model",
        "items": [{"role": "user", "content": "hi"}],
        "updated_at": "t",
    }
    cm.append_trail.return_value = None
    cm.put_agent_state.return_value = {}
    cm.patch_rt.return_value = {}
    # _cm_fetch fetcher_map / dialog targets — 임의 canned
    cm.get_persona_dialog.return_value = {"dialog": True}
    cm.get_invention_object_model.return_value = {"iom": True}
    cm.get_concept_discovery_stack.return_value = {"cds": True}
    cm.get_concept_maturity_model.return_value = {"cmm": True}
    cm.get_conversation.return_value = {"conv": True}
    cm.get_user_roadmap.return_value = [{"id": "r1"}]
    return cm


def _install(
    monkeypatch,
    cm: AsyncMock,
    sess: _FakeSession,
    *,
    compose=None,
    fetch_tools=None,
    tool_handlers: dict[str, Any] | None = None,
):
    """dispatcher namespace 협력자 일괄 주입."""
    monkeypatch.setattr(dispatcher, "get_cm_client", lambda: cm)
    monkeypatch.setattr(dispatcher, "create_llm_session", lambda *a, **k: sess)

    if fetch_tools is None:

        async def _ft_a():  # noqa: ANN202
            return {}

        async def _ft_b():  # noqa: ANN202
            return {}

        fetch_tools = [_ft_a, _ft_b]
    monkeypatch.setattr(dispatcher, "make_fetch_tools", lambda *a, **k: fetch_tools)

    if compose is None:

        async def compose(**kwargs: Any):  # noqa: ANN202
            return "PROMPT"

    monkeypatch.setattr(dispatcher, "compose_prompt", compose)

    handlers = tool_handlers or {}
    monkeypatch.setattr(dispatcher.tools, "get", lambda name: handlers.get(name))
    monkeypatch.setattr(dispatcher.settings, "ACTOR_ID", "actor-test")
    # persona 수락 집합 = engine.config personas (suite 가 ENGINE_CONFIG_FILE 주입 — 1~6)


# busy 1-slot 테스트 폐기 — 동시성은 src/slots.py (persona/tool 풀, test_slots.py 가 커버).


def test_accepts_persona_uses_engine_config(monkeypatch):
    """수락 집합 = engine.config personas (구 ACTOR_PERSONAS env 폐기 — unified)."""
    from src import engine_config

    monkeypatch.setattr(engine_config, "persona_ids", lambda: [3, 4])
    assert dispatcher._accepts_persona(3) is True
    assert dispatcher._accepts_persona(1) is False


# ── handle() happy path ──────────────────────────────────────────────────────


def test_handle_happy_path_event_order_and_calls(monkeypatch):
    rt = {
        "persona": 1,
        "step_id": "s0",
        "pipeline_id": "P01.R00.X",
        "input": _base_rt_input(),
    }
    cm = _make_cm(rt)
    sess = _FakeSession(result={"text": "done", "structured": {"a": 9}})
    _install(monkeypatch, cm, sess)

    chunks = asyncio.run(_drain(dispatcher.handle(_U, _INV, _CH, _RT, 1)))
    events = _parse_events(chunks)
    names = [n for n, _ in events]
    assert names == ["started", "progress", "result"]

    started = events[0][1]
    assert started == {"rt_id": _RT, "actor_id": "actor-test"}

    progress = events[1][1]
    assert progress["phase"] == "llm_call_started"
    assert progress["tools_loaded"] == []
    # fetch_tools 이름이 progress 에 노출
    assert len(progress["fetch_tools"]) == 2
    assert "media_parts" not in progress

    result = events[2][1]
    assert result == {"text": "done", "structured": {"a": 9}}

    # persist 호출 검증 — envelope 통째 (컨텍스트 ②)
    cm.put_agent_state.assert_awaited_once()
    pa_args = cm.put_agent_state.await_args.args
    assert pa_args[:4] == (_U, _INV, 1, _CH)
    assert pa_args[4] == sess.export_state()
    assert pa_args[4]["items"] == [{"role": "assistant", "content": "ok"}]

    cm.patch_rt.assert_awaited_once()
    pr_args = cm.patch_rt.await_args.args
    assert pr_args[:5] == (_U, _INV, 1, _CH, _RT)
    assert pr_args[5] == {"output": {"text": "done", "structured": {"a": 9}}, "state": "done"}

    # sess.run 이 prompt + tools + function_tools + media_refs 로 호출됨
    assert sess.run_kwargs is not None
    assert sess.run_kwargs["prompt"] == "PROMPT"
    assert sess.run_kwargs["response_schema"] == {"required": ["a"]}
    assert sess.run_kwargs["context"] == {"steps": {"s0": {"text": "prev"}}}
    assert len(sess.run_kwargs["function_tools"]) == 2
    assert sess.run_kwargs["media_refs"] == []
    assert "media_parts" not in sess.run_kwargs

    # trail llm_input_prepared 한 번
    cm.append_trail.assert_awaited_once()
    trail_event = cm.append_trail.await_args.args[4]
    assert trail_event["event"] == "llm_input_prepared"
    assert trail_event["sdk"] == "fake-sdk"
    assert trail_event["model"] == "fake-model"
    assert trail_event["prompt_chars"] == len("PROMPT")
    assert trail_event["context_steps_keys"] == ["s0"]
    assert trail_event["has_response_schema"] is True
    assert trail_event["response_schema_required"] == ["a"]
    assert trail_event["media_refs_count"] == 0


def test_handle_uses_dispatch_persona_for_get_rt(monkeypatch):
    """persona 는 dispatch body 가 전달 — 그 persona dir 에서 직접 get_rt (brute-force 순회 폐기, 3a)."""
    rt = {"persona": 3, "step_id": "s0", "pipeline_id": "P03.R00.X", "input": _base_rt_input()}
    cm = _make_cm(rt)
    sess = _FakeSession()
    _install(monkeypatch, cm, sess)

    chunks = asyncio.run(_drain(dispatcher.handle(_U, _INV, _CH, _RT, 3)))
    names = [n for n, _ in _parse_events(chunks)]
    assert names == ["started", "progress", "result"]
    # get_rt 가 전달된 persona(3) 로 정확히 1회 (순회 없음)
    cm.get_rt.assert_awaited_once()
    assert cm.get_rt.await_args.args[2] == 3
    assert cm.put_agent_state.await_args.args[2] == 3


# ── handle() error branches ──────────────────────────────────────────────────


def test_handle_rt_not_found(monkeypatch):
    """get_rt None → error (해당 persona dir 에 RT 없음)."""
    cm = _make_cm(None)
    sess = _FakeSession()
    _install(monkeypatch, cm, sess)

    chunks = asyncio.run(_drain(dispatcher.handle(_U, _INV, _CH, _RT, 1)))
    events = _parse_events(chunks)
    assert [n for n, _ in events] == ["started", "error"]
    assert "not found for persona 1" in events[1][1]["error"]["message"]
    cm.put_agent_state.assert_not_awaited()


def test_handle_persona_not_handled(monkeypatch):
    """dispatch persona=9 — engine.config 미등재 → persona not handled error (get_rt 전 차단)."""
    cm = AsyncMock()
    sess = _FakeSession()
    _install(monkeypatch, cm, sess)

    chunks = asyncio.run(_drain(dispatcher.handle(_U, _INV, _CH, _RT, 9)))
    events = _parse_events(chunks)
    assert [n for n, _ in events] == ["started", "error"]
    assert "persona 9 not handled" in events[1][1]["error"]["message"]
    # _accepts_persona 가 먼저 → get_rt / agent_state 미호출
    cm.get_rt.assert_not_awaited()
    cm.get_agent_state.assert_not_awaited()


def test_handle_legacy_agent_state_fail_loud(monkeypatch):
    """구 평문 agent_state(messages 비어있지 않음) → RuntimeError → SSE error (컨텍스트 ②)."""
    rt = {"persona": 1, "step_id": "s0", "pipeline_id": "P01.R00.X", "input": _base_rt_input()}
    cm = _make_cm(rt)
    cm.get_agent_state.return_value = {
        "persona": 1,
        "messages": [{"role": "user", "content": "old"}],
        "updated_at": "t",
    }
    sess = _FakeSession()
    _install(monkeypatch, cm, sess)

    chunks = asyncio.run(_drain(dispatcher.handle(_U, _INV, _CH, _RT, 1)))
    events = _parse_events(chunks)
    assert [n for n, _ in events] == ["started", "error"]
    assert "legacy agent_state" in events[1][1]["error"]["message"]
    cm.put_agent_state.assert_not_awaited()


def test_handle_passes_parsed_prior_state_to_session(monkeypatch):
    """create_llm_session 이 parse_agent_state 결과(envelope)를 prior_state 로 수령."""
    rt = {"persona": 1, "step_id": "s0", "pipeline_id": "P01.R00.X", "input": _base_rt_input()}
    cm = _make_cm(rt)
    sess = _FakeSession()
    _install(monkeypatch, cm, sess)
    captured: dict[str, Any] = {}

    def _create(persona, prior_state=None, **kwargs):
        captured["persona"] = persona
        captured["prior_state"] = prior_state
        return sess

    monkeypatch.setattr(dispatcher, "create_llm_session", _create)
    asyncio.run(_drain(dispatcher.handle(_U, _INV, _CH, _RT, 1)))
    assert captured["persona"] == 1
    assert captured["prior_state"] == {
        "schema_version": 1,
        "vendor": "fixture",
        "model": "fake-model",
        "items": [{"role": "user", "content": "hi"}],
    }


def test_handle_composer_keys_missing_raises(monkeypatch):
    """RT.input 에 inject_context_spec / persona_prompt 둘 다 없으면 RuntimeError→error."""
    rt = {
        "persona": 1,
        "step_id": "s0",
        "pipeline_id": "P01.R00.X",
        "input": {"available_tools": []},
    }
    cm = _make_cm(rt)
    sess = _FakeSession()
    _install(monkeypatch, cm, sess)

    chunks = asyncio.run(_drain(dispatcher.handle(_U, _INV, _CH, _RT, 1)))
    events = _parse_events(chunks)
    assert [n for n, _ in events] == ["started", "error"]
    assert "composer keys" in events[1][1]["error"]["message"]


def test_handle_only_persona_prompt_passes_key_check(monkeypatch):
    """persona_prompt 만 있어도 (inject_context_spec 없어도) 키 검증 통과."""
    inp = _base_rt_input()
    inp.pop("inject_context_spec")
    rt = {"persona": 1, "step_id": "s0", "pipeline_id": "P01.R00.X", "input": inp}
    cm = _make_cm(rt)
    sess = _FakeSession()
    _install(monkeypatch, cm, sess)

    chunks = asyncio.run(_drain(dispatcher.handle(_U, _INV, _CH, _RT, 1)))
    names = [n for n, _ in _parse_events(chunks)]
    assert names[-1] == "result"


def test_handle_sess_run_exception_yields_error(monkeypatch):
    """sess.run 예외 → 바깥 except → error 이벤트 (started, progress 뒤)."""
    rt = {"persona": 1, "step_id": "s0", "pipeline_id": "P01.R00.X", "input": _base_rt_input()}
    cm = _make_cm(rt)
    sess = _FakeSession(raise_on_run=True)
    _install(monkeypatch, cm, sess)

    chunks = asyncio.run(_drain(dispatcher.handle(_U, _INV, _CH, _RT, 1)))
    events = _parse_events(chunks)
    assert [n for n, _ in events] == ["started", "progress", "error"]
    assert "llm boom" in events[2][1]["error"]["message"]
    cm.put_agent_state.assert_not_awaited()


# ── tool loading ──────────────────────────────────────────────────────────────


def test_handle_loaded_tools_and_missing_tool_warns(monkeypatch):
    """available_tools 중 등록된 것만 loaded, 미등록은 warning 후 skip."""
    inp = _base_rt_input(available_tools=["kipris.search_patents", "nope.missing"])
    rt = {"persona": 1, "step_id": "s0", "pipeline_id": "P01.R00.X", "input": inp}
    cm = _make_cm(rt)
    sess = _FakeSession()

    def _handler(args):  # noqa: ANN001, ANN202
        return {}

    _install(monkeypatch, cm, sess, tool_handlers={"kipris.search_patents": _handler})

    chunks = asyncio.run(_drain(dispatcher.handle(_U, _INV, _CH, _RT, 1)))
    events = _parse_events(chunks)
    progress = next(d for n, d in events if n == "progress")
    assert progress["tools_loaded"] == ["kipris.search_patents"]
    # sess.run 의 tools 에 등록된 1개만
    assert [t["name"] for t in sess.run_kwargs["tools"]] == ["kipris.search_patents"]
    assert sess.run_kwargs["tools"][0]["handler"] is _handler


# ── media_refs passthrough (binary 인라인 폐기 — media_refs 만 보존) ──────────────


def test_handle_media_refs_passthrough_to_run_and_trail(monkeypatch):
    """media_refs 는 rt_input 에서 sess.run + trail media_refs_count 로 그대로 전달."""
    refs = [{"media_id": "m1"}, {"media_id": "m2"}]
    rt = {
        "persona": 1,
        "step_id": "s0",
        "pipeline_id": "P01.R00.X",
        "input": _base_rt_input(media_refs=refs),
    }
    cm = _make_cm(rt)
    sess = _FakeSession()
    _install(monkeypatch, cm, sess)

    chunks = asyncio.run(_drain(dispatcher.handle(_U, _INV, _CH, _RT, 1)))
    events = _parse_events(chunks)
    progress = next(d for n, d in events if n == "progress")
    assert "media_parts" not in progress
    assert sess.run_kwargs["media_refs"] == refs
    assert "media_parts" not in sess.run_kwargs
    trail_event = cm.append_trail.await_args.args[4]
    assert trail_event["media_refs_count"] == 2


# ── _cm_fetch closure (compose_prompt fake 가 직접 구동) ──────────────────────


def test_handle_cm_fetch_closure_all_resource_branches(monkeypatch):
    """compose_prompt fake 가 dispatcher 의 _cm_fetch 를 다양한 path 로 호출 → 모든 분기 커버."""
    rt = {"persona": 2, "step_id": "s0", "pipeline_id": "P02.R00.X", "input": _base_rt_input()}
    cm = _make_cm(rt)
    sess = _FakeSession()

    captured: dict[str, Any] = {}

    async def _compose(**kwargs: Any):
        cm_fetch = kwargs["cm_fetch"]
        # 1) dialogs/<digit>.<name>.json → get_persona_dialog(int, name)
        captured["dialog_digit"] = await cm_fetch("dialogs/3.analysis.json")
        # 2) dialogs/<name> (digit 아님) → persona 채택 분기
        captured["dialog_persona"] = await cm_fetch("dialogs/research")
        # 3) RFC6901 pointer 있는 resource
        captured["iom_ptr"] = await cm_fetch("invention_object_model/claims/0")
        # 4) pointer 없는 resource
        captured["cds"] = await cm_fetch("concept_discovery_stack")
        captured["cmm"] = await cm_fetch("concept_maturity_model")
        captured["conv"] = await cm_fetch("conversation")
        captured["ur"] = await cm_fetch("user_roadmap")
        return "PROMPT-CM"

    _install(monkeypatch, cm, sess, compose=_compose)

    chunks = asyncio.run(_drain(dispatcher.handle(_U, _INV, _CH, _RT, 2)))
    assert [n for n, _ in _parse_events(chunks)][-1] == "result"

    # dialogs/3.analysis.json → persona 3, name analysis
    assert captured["dialog_digit"] == {"dialog": True}
    pd_call = cm.get_persona_dialog.await_args_list[0]
    assert pd_call.args == (_U, _INV, 3, "analysis")

    # dialogs/research (no digit) → persona 채택 (rt.persona=2)
    assert captured["dialog_persona"] == {"dialog": True}
    pd_call2 = cm.get_persona_dialog.await_args_list[1]
    assert pd_call2.args == (_U, _INV, 2, "research")

    # invention_object_model/claims/0 → pointer="/claims/0"
    cm.get_invention_object_model.assert_awaited_once()
    assert cm.get_invention_object_model.await_args.kwargs == {"pointer": "/claims/0"}
    # pointer 없는 것들 → pointer=""
    assert cm.get_concept_discovery_stack.await_args.kwargs == {"pointer": ""}
    assert cm.get_user_roadmap.await_args.kwargs == {"pointer": ""}
    assert captured["ur"] == [{"id": "r1"}]


def test_handle_cm_fetch_dot_path_rejected(monkeypatch):
    """cm:// path 에 dot('.') 표기 → RuntimeError (RFC6901 강제)."""
    rt = {"persona": 1, "step_id": "s0", "pipeline_id": "P01.R00.X", "input": _base_rt_input()}
    cm = _make_cm(rt)
    sess = _FakeSession()

    async def _compose(**kwargs: Any):
        await kwargs["cm_fetch"]("invention_object_model.claims.0")
        return "PROMPT"

    _install(monkeypatch, cm, sess, compose=_compose)

    chunks = asyncio.run(_drain(dispatcher.handle(_U, _INV, _CH, _RT, 1)))
    events = _parse_events(chunks)
    assert events[-1][0] == "error"
    assert "dot-path" in events[-1][1]["error"]["message"]


def test_handle_cm_fetch_unknown_resource_raises(monkeypatch):
    """cm:// 미지원 resource head → RuntimeError."""
    rt = {"persona": 1, "step_id": "s0", "pipeline_id": "P01.R00.X", "input": _base_rt_input()}
    cm = _make_cm(rt)
    sess = _FakeSession()

    async def _compose(**kwargs: Any):
        await kwargs["cm_fetch"]("totally_unknown")
        return "PROMPT"

    _install(monkeypatch, cm, sess, compose=_compose)

    chunks = asyncio.run(_drain(dispatcher.handle(_U, _INV, _CH, _RT, 1)))
    events = _parse_events(chunks)
    assert events[-1][0] == "error"
    assert "미지원 resource" in events[-1][1]["error"]["message"]


def test_handle_cm_fetch_dialog_persona_zero_returns_none(monkeypatch):
    """dialogs/<name> 인데 persona 가 falsy(0) 면 None 반환.

    persona 메타가 0 이 되도록: rt.persona 없음 (dispatch persona 는 1 이상이라 0 불가).
    대신 직접 persona=0 경로는 도달불가 → digit 아닌 단일 token (len(parts)==1) 으로
    persona 채택 분기의 get_persona_dialog 예외 → None 도 함께 검증.
    """
    rt = {"persona": 1, "step_id": "s0", "pipeline_id": "P01.R00.X", "input": _base_rt_input()}
    cm = _make_cm(rt)
    cm.get_persona_dialog.side_effect = RuntimeError("dialog boom")
    sess = _FakeSession()

    captured: dict[str, Any] = {}

    async def _compose(**kwargs: Any):
        # persona truthy(1) + get_persona_dialog raise → except → None
        captured["v"] = await kwargs["cm_fetch"]("dialogs/research")
        return "PROMPT"

    _install(monkeypatch, cm, sess, compose=_compose)

    chunks = asyncio.run(_drain(dispatcher.handle(_U, _INV, _CH, _RT, 1)))
    assert [n for n, _ in _parse_events(chunks)][-1] == "result"
    assert captured["v"] is None


def test_handle_cm_fetch_dialog_digit_single_token_falls_through(monkeypatch):
    """dialogs/5 (digit 이지만 len(parts)==1) → digit-branch 미충족, persona 채택 분기."""
    rt = {"persona": 4, "step_id": "s0", "pipeline_id": "P04.R00.X", "input": _base_rt_input()}
    cm = _make_cm(rt)
    sess = _FakeSession()

    captured: dict[str, Any] = {}

    async def _compose(**kwargs: Any):
        captured["v"] = await kwargs["cm_fetch"]("dialogs/5")
        return "PROMPT"

    _install(monkeypatch, cm, sess, compose=_compose)
    # persona 4 = engine.config 등재 (1~6) — 별도 수용 설정 불요 (unified)

    chunks = asyncio.run(_drain(dispatcher.handle(_U, _INV, _CH, _RT, 4)))
    assert [n for n, _ in _parse_events(chunks)][-1] == "result"
    # persona=4 채택, name="5" (parts[0])
    pd_call = cm.get_persona_dialog.await_args_list[-1]
    assert pd_call.args == (_U, _INV, 4, "5")
    assert captured["v"] == {"dialog": True}


def test_handle_uses_real_compose_prompt_no_context(monkeypatch):
    """compose_prompt 를 mock 하지 않고 실제 호출 (inline instructions, cm:// 없음).

    _cm_fetch 가 정의되지만 호출되지 않는 경로 — 실 composer 통합 1건."""
    inp = _base_rt_input(
        inject_context_spec={},
        recommended_context_spec={},
        fragments={"note": "reusable prose"},
        instructions={"inline": "do X then Y"},
    )
    rt = {"persona": 1, "step_id": "s0", "pipeline_id": "P01.R00.X", "input": inp}
    cm = _make_cm(rt)
    sess = _FakeSession()
    # compose 미지정 → 실 compose_prompt 사용 (단, dispatcher.compose_prompt 는 실 함수)
    monkeypatch.setattr(dispatcher, "get_cm_client", lambda: cm)
    monkeypatch.setattr(dispatcher, "create_llm_session", lambda *a, **k: sess)
    monkeypatch.setattr(dispatcher, "make_fetch_tools", lambda *a, **k: [])
    monkeypatch.setattr(dispatcher.tools, "get", lambda name: None)
    monkeypatch.setattr(dispatcher.settings, "ACTOR_ID", "actor-test")
    # persona 수락 집합 = engine.config personas (suite 가 ENGINE_CONFIG_FILE 주입 — 1~6)

    chunks = asyncio.run(_drain(dispatcher.handle(_U, _INV, _CH, _RT, 1)))
    events = _parse_events(chunks)
    assert events[-1][0] == "result"
    # 실 compose_prompt 가 [PERSONA]/[FRAGMENTS]/[TASK] 합성 → prompt 에 반영
    prompt = sess.run_kwargs["prompt"]
    assert "[PERSONA]" in prompt
    assert "reusable prose" in prompt
    assert "do X then Y" in prompt
