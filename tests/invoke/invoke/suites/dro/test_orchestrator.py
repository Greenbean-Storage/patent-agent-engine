"""200.DRO orchestrator — step/RT/tool 실행 헬퍼 (invoke 단위).

대상: 200.DRO/src/orchestrator.py 의 step 실행 헬퍼(_run_steps/_run_one_step/_dispatch_llm_step/
_dispatch_rt/_exec_tool_call/_build_rt_input/_enqueue_all_rts 등) + build_chain_context.
**chain 구동(run_chain facade·_drive_chain·worker)은 `test_worker.py`** (C1 — 이벤트 구동 worker).
외부 의존(CMClient / dispatcher / event_sse / load_pipeline / resolve_dispatch /
substitute_placeholders) 은 모두 fake/mock 으로 교체해 분기·에러경로를 직접 assert.

전략:
  - get_cm_client       → AsyncMock CMClient (FakeCM) 주입. 호출 인자/순서 검사.
  - dispatch_with_retry → 가짜 LLM 결과 반환 (structured unwrap 분기 커버).
  - dispatch_tool       → 가짜 tool 응답 (status/result/payload 요약 분기 커버).
  - event_sse.emit_raw  → _EmitRecorder 로 raw emit 기록 (RAW only — 매핑은 Nexus).
  - load_pipeline       → in-test pipeline dict (LLM / tool / nested-parallel / dispatch_to).
  - resolve_dispatch    → 다음 pipeline_id list 제어.

async 는 asyncio.run(...) 로 (pytest-asyncio mark 없이; 기존 suite 패턴).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "200.DRO"))
sys.path.insert(0, str(ROOT / "shared"))

import src.orchestrator as O  # noqa: E402


# ── 공통 fakes ──────────────────────────────────────────────────────────────


class _EmitRecorder:
    """event_sse.emit_raw 대체 — raw emit 호출 기록 (DRO 는 RAW only — 매핑은 Nexus).

    emits = list of (user_id, work_id, event_type, payload). persona/step 은 meta 에.
    """

    def __init__(self) -> None:
        self.emits: list[tuple[str, str, str, dict]] = []
        self.meta: list[dict] = []

    async def __call__(self, user_id, work_id, event_type, payload, *, persona=None, step=None):
        self.emits.append((user_id, work_id, event_type, payload))
        self.meta.append({"persona": persona, "step": step})

    def of_type(self, t: str) -> list[tuple]:
        return [e for e in self.emits if e[2] == t]


def _make_cm() -> AsyncMock:
    """AsyncMock CMClient — 모든 async 메서드 default AsyncMock. 필요분만 return_value 지정."""
    cm = AsyncMock()
    cm.persona_queue_pop.return_value = {"empty": True}
    cm.create_chain.return_value = {"ok": True}
    cm.create_rt.return_value = {"ok": True}
    cm.patch_rt.return_value = {"ok": True}
    cm.patch_chain.return_value = {"ok": True}
    cm.persona_queue_push.return_value = {"ok": True}
    cm.append_trail.return_value = None
    cm.append_conversation.return_value = None
    cm.patch_context_manifest.return_value = {"ok": True}
    return cm


def _install(monkeypatch, *, cm=None) -> tuple[AsyncMock, _EmitRecorder]:
    """orchestrator 의 외부 의존을 fake 로 교체. emit 은 event_sse.emit_raw 기록기로. (cm, rec) 반환."""
    cm = cm or _make_cm()
    rec = _EmitRecorder()
    monkeypatch.setattr(O, "get_cm_client", lambda: cm)
    monkeypatch.setattr(O.event_sse, "emit_raw", rec)
    # 기본: substitute_placeholders 는 입력 그대로 통과 (분기 격리). 필요 테스트가 override.
    monkeypatch.setattr(O, "substitute_placeholders", lambda spec, ctx: spec)
    return cm, rec


# ── _now ────────────────────────────────────────────────────────────────────


def test_now_iso8601():
    s = O._now()
    assert "T" in s and s.endswith("+00:00")


# (구 spawn_chain/progress_chain 테스트는 worker 로 이전 → test_worker.py — C1)


# ── _run_one_step 에러 분기 (직접) ───────────────────────────────────────────


def test_run_one_step_both_instructions_and_tool_raises(monkeypatch):
    _install(monkeypatch)
    step = {"id": "bad", "instructions": {"inline": "x"}, "tool": "t.x"}

    async def _main():
        await O._run_one_step("u", "inv", "c1", step, {"__persona__": 2, "steps": {}})

    with pytest.raises(RuntimeError, match="both 'instructions' and 'tool'"):
        asyncio.run(_main())


def test_run_one_step_neither_raises(monkeypatch):
    _install(monkeypatch)
    step = {"id": "empty"}

    async def _main():
        await O._run_one_step("u", "inv", "c1", step, {"__persona__": 2, "steps": {}})

    with pytest.raises(RuntimeError, match="neither 'instructions' nor 'tool'"):
        asyncio.run(_main())


def test_run_one_step_skips_rehydrated_done_step(monkeypatch):
    """A-3 재시작 복구 — 이미 완료된 step(context.steps 보유)은 재실행 skip."""
    _install(monkeypatch)
    called: list = []

    async def _dispatch_llm_step(*a, **k):
        called.append(1)
        return {}

    monkeypatch.setattr(O, "_dispatch_llm_step", _dispatch_llm_step)
    step = {"id": "s0", "instructions": {"inline": "x"}}
    context = {"__persona__": 2, "steps": {"s0": {"already": "done"}}}

    async def _main():
        await O._run_one_step("u", "inv", "c1", step, context)

    asyncio.run(_main())
    assert called == []  # rehydrate 된 done step → dispatch 안 함


# ── _run_steps unexpected shape ──────────────────────────────────────────────


def test_run_steps_unexpected_shape_raises(monkeypatch):
    _install(monkeypatch)
    ctx = {"__persona__": 2, "steps": {}}

    async def _main():
        await O._run_steps("u", "inv", "c1", ["not-a-step"], ctx)

    with pytest.raises(RuntimeError, match="unexpected step shape: str"):
        asyncio.run(_main())


# ── _dispatch_llm_step — popped non-empty / step_id mismatch ─────────────────


def test_dispatch_llm_step_popped_matches_no_recreate(monkeypatch):
    cm, _rec = _install(monkeypatch)
    # 미리 push 된 RT 와 step_id 일치 + not done → 재생성 없음
    cm.persona_queue_pop.return_value = {"empty": False, "rt_id": "rtX"}
    cm.get_rt.return_value = {
        "rt_id": "rtX",
        "step_id": "s0",
        "input": {"a": 1},
        "state": "pending",
    }
    monkeypatch.setattr(O, "substitute_placeholders", lambda inp, ctx: {"a": 1})

    async def _dispatch(*a, on_event=None, **k):
        return {"text": "ok"}

    monkeypatch.setattr(O, "dispatch_with_retry", _dispatch)
    step = {"id": "s0", "instructions": {"inline": "x"}}
    ctx = {"__persona__": 2, "steps": {}, "inputs": {}, "parent_outputs": {}}

    async def _main():
        return await O._dispatch_llm_step("u", "inv", "c1", step, ctx, 2)

    out = asyncio.run(_main())
    # structured 없음 → result 그대로
    assert out == {"text": "ok"}
    # _create_and_push_rt 안 탔으므로 create_rt 호출 0
    cm.create_rt.assert_not_awaited()


def test_dispatch_llm_step_popped_stale_recreates(monkeypatch):
    cm, _rec = _install(monkeypatch)
    # popped RT 의 step_id 가 현재 step 과 불일치 → 재생성 경로
    cm.persona_queue_pop.return_value = {"empty": False, "rt_id": "old"}
    rt_seq = [
        {"rt_id": "old", "step_id": "OTHER", "state": "pending"},  # mismatch
        {"rt_id": "new", "step_id": "s0", "input": {"a": 2}, "state": "pending"},  # recreated
    ]
    cm.get_rt.side_effect = rt_seq
    monkeypatch.setattr(O, "substitute_placeholders", lambda inp, ctx: dict(inp))

    async def _dispatch(*a, on_event=None, **k):
        return {"text": "z", "structured": [1, 2, 3]}

    monkeypatch.setattr(O, "dispatch_with_retry", _dispatch)
    step = {"id": "s0", "instructions": {"inline": "x"}}
    ctx = {"__persona__": 2, "steps": {}, "inputs": {}, "parent_outputs": {}}

    async def _main():
        return await O._dispatch_llm_step("u", "inv", "c1", step, ctx, 2)

    out = asyncio.run(_main())
    # structured 가 list → unwrap
    assert out == [1, 2, 3]
    cm.create_rt.assert_awaited()  # 재생성됨


def test_dispatch_llm_step_substituted_non_dict(monkeypatch):
    cm, _rec = _install(monkeypatch)
    cm.persona_queue_pop.return_value = {"empty": True}
    cm.get_rt.return_value = {"rt_id": "r", "step_id": "s0", "input": "raw", "state": "pending"}
    # substitute 가 dict 아닌 값 반환 → context 주입 분기 skip
    monkeypatch.setattr(O, "substitute_placeholders", lambda inp, ctx: "scalar-out")

    async def _dispatch(*a, on_event=None, **k):
        return {"text": "ok"}

    monkeypatch.setattr(O, "dispatch_with_retry", _dispatch)
    step = {"id": "s0", "instructions": {"inline": "x"}}
    ctx = {"__persona__": 2, "steps": {}, "inputs": {}, "parent_outputs": {}}

    async def _main():
        return await O._dispatch_llm_step("u", "inv", "c1", step, ctx, 2)

    out = asyncio.run(_main())
    assert out == {"text": "ok"}
    # patch_rt 의 input 이 scalar (context 안 박힘)
    patched_input = cm.patch_rt.await_args_list[0].args[5]["input"]
    assert patched_input == "scalar-out"


# ── _resolve_persona ─────────────────────────────────────────────────────────


def test_resolve_persona_present_and_missing():
    assert O._resolve_persona({"id": "x"}, {"__persona__": 3}) == 3
    with pytest.raises(RuntimeError, match="persona not defined"):
        O._resolve_persona({"id": "x"}, {})


# ── _contract_loader — unavailable cached as False ───────────────────────────


def test_contract_loader_caches_false_on_import_failure(monkeypatch):
    monkeypatch.setattr(O, "_CONTRACT_LOADER", None)

    # venezia_contracts.ContractLoader import 를 실패시킴
    import builtins

    real_import = builtins.__import__

    def _fake_import(name, *a, **k):
        if name == "venezia_contracts":
            raise ImportError("nope")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    assert O._contract_loader() is None
    # 두번째 호출은 _CONTRACT_LOADER is False 분기
    assert O._contract_loader() is None
    assert O._CONTRACT_LOADER is False
    monkeypatch.setattr(O, "_CONTRACT_LOADER", None)


# ── _validate_rt_schema ──────────────────────────────────────────────────────


def test_validate_rt_schema_loader_none_returns_early(monkeypatch):
    monkeypatch.setattr(O, "_contract_loader", lambda: None)
    cm = _make_cm()

    async def _main():
        await O._validate_rt_schema(cm, "u", "inv", 2, "c1", {"rt_id": "r"})

    asyncio.run(_main())
    cm.append_trail.assert_not_awaited()


def test_validate_rt_schema_valid_returns_no_trail(monkeypatch):
    class _Loader:
        def validate(self, contract, rt):
            return True  # truthy → valid

    monkeypatch.setattr(O, "_contract_loader", lambda: _Loader())
    cm = _make_cm()

    async def _main():
        await O._validate_rt_schema(cm, "u", "inv", 2, "c1", {"rt_id": "r"})

    asyncio.run(_main())
    cm.append_trail.assert_not_awaited()


def test_validate_rt_schema_invalid_appends_violation_trail(monkeypatch):
    class _Result:
        def __bool__(self):
            return False

        errors = ["e1", "e2", "e3", "e4", "e5", "e6"]

    class _Loader:
        def validate(self, contract, rt):
            return _Result()

    monkeypatch.setattr(O, "_contract_loader", lambda: _Loader())
    cm = _make_cm()

    async def _main():
        await O._validate_rt_schema(cm, "u", "inv", 2, "c1", {"rt_id": "r"})

    asyncio.run(_main())
    cm.append_trail.assert_awaited_once()
    ev = cm.append_trail.await_args.args[4]
    assert ev["event"] == "schema_violation"
    assert len(ev["errors"]) == 5  # errors[:5]


def test_validate_rt_schema_invalid_trail_append_failure_swallowed(monkeypatch):
    class _Result:
        def __bool__(self):
            return False

        errors: list = []

    class _Loader:
        def validate(self, contract, rt):
            return _Result()

    monkeypatch.setattr(O, "_contract_loader", lambda: _Loader())
    cm = _make_cm()
    cm.append_trail.side_effect = RuntimeError("trail down")

    async def _main():
        await O._validate_rt_schema(cm, "u", "inv", 2, "c1", {"rt_id": "r"})

    # 예외 삼킴 (log.warning) — raise 안 함
    asyncio.run(_main())


# ── _context_with_last_step_flag ─────────────────────────────────────────────


def test_context_with_last_step_flag():
    ctx = {"__last_step_id__": "s9", "x": 1}
    last = O._context_with_last_step_flag({"id": "s9"}, ctx)
    assert last["__is_last_step__"] is True
    not_last = O._context_with_last_step_flag({"id": "s1"}, ctx)
    assert not_last["__is_last_step__"] is False


# ── _load_output_contract ────────────────────────────────────────────────────


def test_load_output_contract_no_id_or_persona():
    assert O._load_output_contract("", 2) is None
    assert O._load_output_contract("some", None) is None


def test_load_output_contract_loads_real_schema(monkeypatch, tmp_path):
    # /contracts 미존재 → PIPELINES_DIR.parent / @contracts fallback 경로 사용.
    contracts = tmp_path / "@contracts"
    stage_dir = contracts / "02.director" / "stages"
    stage_dir.mkdir(parents=True)
    (stage_dir / "my-stage.schema.json").write_text('{"type":"object"}', encoding="utf-8")
    # PIPELINES_DIR.parent == tmp_path 가 되도록
    monkeypatch.setattr(O.settings, "PIPELINES_DIR", str(tmp_path / "@pipelines"))
    # /contracts 와 /app/@contracts 존재 안 하게 하기 위해 Path.exists 를 건드리지 않고
    # tmp_path 기반 fallback 만 존재하므로 자연히 그 경로로 감.
    out = O._load_output_contract("my-stage", 2)
    assert out == {"type": "object"}


def test_load_output_contract_missing_returns_none(monkeypatch, tmp_path):
    contracts = tmp_path / "@contracts"
    (contracts / "02.director" / "stages").mkdir(parents=True)
    monkeypatch.setattr(O.settings, "PIPELINES_DIR", str(tmp_path / "@pipelines"))
    # 존재하지 않는 contract_id → None (schema_file.exists() False → loop 끝 → None)
    assert O._load_output_contract("nope", 2) is None


def test_load_output_contract_no_root_returns_none(monkeypatch, tmp_path):
    # /contracts, fallback, /app/@contracts 모두 없음 → None
    monkeypatch.setattr(O.settings, "PIPELINES_DIR", str(tmp_path / "no" / "@pipelines"))
    assert O._load_output_contract("x", 2) is None


def test_load_output_contract_invalid_json_returns_none(monkeypatch, tmp_path):
    contracts = tmp_path / "@contracts"
    stage_dir = contracts / "02.director" / "stages"
    stage_dir.mkdir(parents=True)
    (stage_dir / "bad.schema.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(O.settings, "PIPELINES_DIR", str(tmp_path / "@pipelines"))
    assert O._load_output_contract("bad", 2) is None


# ── _build_rt_input ──────────────────────────────────────────────────────────


def test_build_rt_input_with_dispatch_choice_guide():
    step = {
        "id": "last",
        "instructions": {"inline": "x"},
        "system_prompt": "sys",
    }
    ctx = {
        "__persona__": 2,
        "__is_last_step__": True,
        "__pipeline_dispatch_to__": {"actions": [["P03.R00.A", "P03.R00.B"], [], "not-a-list"]},
        "inputs": {"i": 1},
        "parent_outputs": {"p": 2},
    }
    out = O._build_rt_input(step, ctx)
    guide = out["dispatch_choice_guide"]
    assert guide[0] == "다음 파이프라인: P03.R00.A, P03.R00.B"
    assert guide[1] == "(exit — chain 종료)"
    assert 2 not in guide  # non-list action 은 skip
    assert out["persona_prompt"] == "sys"
    assert "llm_spec" not in out  # D-2: llm_spec 제거 (DRO LLM-agnostic)
    assert out["context"] == {"inputs": {"i": 1}, "parent_outputs": {"p": 2}}


def test_build_rt_input_no_guide_when_single_action():
    step = {"id": "x", "instructions": {"inline": "y"}}
    ctx = {
        "__persona__": 2,
        "__is_last_step__": True,
        "__pipeline_dispatch_to__": {"actions": [["P03.R00.A"]]},  # 단일 → guide 없음
    }
    out = O._build_rt_input(step, ctx)
    assert out["dispatch_choice_guide"] is None


def test_build_rt_input_with_output_contract(monkeypatch):
    monkeypatch.setattr(O, "_load_output_contract", lambda cid, p: {"type": "object"})
    step = {"id": "x", "instructions": {"inline": "y"}, "output_contract": "stage-1"}
    out = O._build_rt_input(step, {"__persona__": 2})
    assert out["response_schema"] == {"type": "object"}
    assert out["step_definition"]["output_contract"] == "stage-1"


# ── _create_and_push_rt ──────────────────────────────────────────────────────


def test_create_and_push_rt_builds_and_pushes(monkeypatch):
    cm, _rec = _install(monkeypatch)
    monkeypatch.setattr(O, "_validate_rt_schema", AsyncMock(return_value=None))
    step = {"id": "s0", "instructions": {"inline": "x"}}
    ctx = {"__persona__": 2, "__pipeline_id__": "P02.R00.X", "__last_step_id__": "s0"}

    async def _main():
        return await O._create_and_push_rt("u", "inv", "c1", step, ctx)

    rt_id = asyncio.run(_main())
    assert isinstance(rt_id, str) and len(rt_id) > 0
    cm.create_rt.assert_awaited_once()
    cm.persona_queue_push.assert_awaited_once()
    created = cm.create_rt.await_args.args[4]
    assert created["step_id"] == "s0"
    assert created["pipeline_id"] == "P02.R00.X"
    assert created["state"] == "pending"


# ── _enqueue_all_rts ─────────────────────────────────────────────────────────


def test_enqueue_all_rts_dict_and_nested_list(monkeypatch):
    cm, rec = _install(monkeypatch)
    monkeypatch.setattr(O, "_validate_rt_schema", AsyncMock(return_value=None))
    steps = [
        {"id": "a", "instructions": {"inline": "x"}},  # dict LLM step
        [{"id": "b", "instructions": {"inline": "y"}}, {"id": "c", "tool": "t.x"}],  # list group
        {"id": "d", "tool": "t.y"},  # dict tool step
    ]
    ctx = {"__persona__": 2, "__pipeline_id__": "P02.R00.X", "__last_step_id__": "d"}

    async def _main():
        await O._enqueue_all_rts("u", "inv", "c1", steps, ctx)

    asyncio.run(_main())
    # tool=RT 통일(N-7) — 모든 step 이 RT: a(LLM) b(LLM) c(tool) d(tool) = 4
    assert cm.create_rt.await_count == 4
    # rt_enqueued raw SSE emit 4회 (RAW only — Nexus 가 매핑)
    assert sum(1 for e in rec.emits if e[2] == "rt_enqueued") == 4
    assert len(rec.of_type("rt_enqueued")) == 4


# ── _dispatch_rt — 성공 + 실패 경로 ──────────────────────────────────────────


def test_dispatch_rt_success_appends_done(monkeypatch):
    cm, rec = _install(monkeypatch)

    async def _dispatch(persona, chain_id, rt_id, user_id, work_id, on_event=None):
        await on_event({"type": "result", "data": {"text": "yo"}})
        return {"text": "yo"}

    monkeypatch.setattr(O, "dispatch_with_retry", _dispatch)

    async def _main():
        return await O._dispatch_rt(
            "u",
            "inv",
            "c1",
            "rt1",
            2,
            {"id": "s0", "display_status": {"ko": "처리 중", "en": "Working"}},
        )

    out = asyncio.run(_main())
    assert out == {"text": "yo"}
    # rt_started + rt_completed trail + done patch_rt + lease release finally
    events = [c.args[4].get("event") for c in cm.append_trail.await_args_list]
    assert "rt_started" in events and "rt_completed" in events
    cm.persona_queue_release.assert_awaited_once_with("u", "inv", 2, "rt1")
    # _on_event 의 rt_result raw SSE emit
    assert any(e[2] == "rt_result" for e in rec.emits)


def test_dispatch_rt_failure_raises_and_marks_failed(monkeypatch):
    cm, rec = _install(monkeypatch)

    async def _dispatch(*a, on_event=None, **k):
        raise RuntimeError("dispatch boom")

    monkeypatch.setattr(O, "dispatch_with_retry", _dispatch)

    async def _main():
        await O._dispatch_rt(
            "u",
            "inv",
            "c1",
            "rt1",
            2,
            {"id": "s0", "display_status": {"ko": "처리 중", "en": "Working"}},
        )

    with pytest.raises(RuntimeError, match="dispatch boom"):
        asyncio.run(_main())
    # failed patch_rt + rt_failed trail
    failed_states = [c.args[5].get("state") for c in cm.patch_rt.await_args_list]
    assert "failed" in failed_states
    events = [c.args[4].get("event") for c in cm.append_trail.await_args_list]
    assert "rt_failed" in events
    # finally — 본인 rt_id lease release 호출됨
    cm.persona_queue_release.assert_awaited_once_with("u", "inv", 2, "rt1")


def test_dispatch_rt_on_event_non_dict_data(monkeypatch):
    cm, rec = _install(monkeypatch)

    async def _dispatch(persona, chain_id, rt_id, user_id, work_id, on_event=None):
        # data 가 dict 아님 → map_chain 에 {} 전달 분기
        await on_event({"type": "progress", "data": "string-data"})
        return {"ok": True}

    monkeypatch.setattr(O, "dispatch_with_retry", _dispatch)

    async def _main():
        return await O._dispatch_rt(
            "u",
            "inv",
            "c1",
            "rt1",
            2,
            {"id": "s0", "display_status": {"ko": "처리 중", "en": "Working"}},
        )

    out = asyncio.run(_main())
    assert out == {"ok": True}
    # rt_progress payload 가 {} 로 정규화 (non-dict Actor data)
    progress = rec.of_type("rt_progress")
    assert progress and progress[0][3] == {}


def test_dispatch_rt_lease_release_failure_swallowed(monkeypatch):
    cm, rec = _install(monkeypatch)
    cm.persona_queue_release.side_effect = RuntimeError("release boom")

    async def _dispatch(persona, chain_id, rt_id, user_id, work_id, on_event=None):
        return {"ok": 1}

    monkeypatch.setattr(O, "dispatch_with_retry", _dispatch)

    async def _main():
        return await O._dispatch_rt(
            "u",
            "inv",
            "c1",
            "rt1",
            2,
            {"id": "s0", "display_status": {"ko": "처리 중", "en": "Working"}},
        )

    # finally 의 lease release 실패가 결과를 깨지 않음
    out = asyncio.run(_main())
    assert out == {"ok": 1}


# ── _summarize_params ────────────────────────────────────────────────────────


def test_summarize_params_all_types():
    params = {
        "none": None,
        "b": True,
        "n": 3,
        "f": 1.5,
        "short": "abc",
        "long": "x" * 100,
        "lst": [
            {"k": "v", "nested": {"a": 1}},  # dict in list → nested 제거
            "y" * 250,  # 긴 string → 잘림
            "ok",
            42,
        ],
        "dct": {"a": 1, "b": 2},
        "tup": (1, 2),  # 기타 타입
    }
    out = O._summarize_params(params)
    assert out["none"] is None
    assert out["b"] is True
    assert out["n"] == 3
    assert out["f"] == 1.5
    assert out["short"] == "abc"
    assert out["long"].endswith("…") and len(out["long"]) == 81
    assert out["lst"]["_len"] == 4
    full = out["lst"]["_full"]
    assert full[0] == {"k": "v"}  # nested dict/list 제거
    assert full[1].endswith("…")
    assert full[2] == "ok"
    assert full[3] == 42
    assert out["dct"] == {"_keys": ["a", "b"]}
    assert out["tup"] == {"_type": "tuple"}


def test_summarize_params_empty():
    assert O._summarize_params(None) == {}


# ── _split_cm_path ───────────────────────────────────────────────────────────


def test_split_cm_path_variants():
    assert O._split_cm_path("invention_object_model") == ("invention_object_model", "")
    assert O._split_cm_path("concept_discovery_stack/purpose") == (
        "concept_discovery_stack",
        "/purpose",
    )
    assert O._split_cm_path("concept_discovery_stack/sub/field") == (
        "concept_discovery_stack",
        "/sub/field",
    )


def test_split_cm_path_dot_path_fails():
    with pytest.raises(RuntimeError, match="dot-path 표기는 폐기"):
        O._split_cm_path("concept_discovery_stack.purpose")


# ── _resolve_inject_context ──────────────────────────────────────────────────


def test_resolve_inject_context_passthrough_non_cm(monkeypatch):
    cm, _rec = _install(monkeypatch)

    async def _main():
        return await O._resolve_inject_context("u", "inv", "c1", {"lit": "plain", "num": 5})

    out = asyncio.run(_main())
    assert out == {"lit": "plain", "num": 5}


def test_resolve_inject_context_dialog_and_resource(monkeypatch):
    cm, _rec = _install(monkeypatch)
    cm.get_persona_dialog.return_value = {"dialog": "d"}
    cm.get_concept_discovery_stack.return_value = {"purpose": "P"}

    async def _main():
        return await O._resolve_inject_context(
            "u",
            "inv",
            "c1",
            {
                "dlg": "cm://dialogs/2.analysis.json",
                "cds": "cm://concept_discovery_stack/purpose",
            },
        )

    out = asyncio.run(_main())
    assert out["dlg"] == {"dialog": "d"}
    cm.get_persona_dialog.assert_awaited_once_with("u", "inv", 2, "analysis")
    assert out["cds"] == {"purpose": "P"}
    cm.get_concept_discovery_stack.assert_awaited_once_with("u", "inv", pointer="/purpose")


def test_resolve_inject_context_dialog_malformed_none(monkeypatch):
    cm, _rec = _install(monkeypatch)

    async def _main():
        # dialogs/ 인데 persona digit 아님 → None
        return await O._resolve_inject_context(
            "u", "inv", "c1", {"dlg": "cm://dialogs/notdigit.json"}
        )

    out = asyncio.run(_main())
    assert out["dlg"] is None


def test_resolve_inject_context_unknown_resource_raises(monkeypatch):
    cm, _rec = _install(monkeypatch)

    async def _main():
        await O._resolve_inject_context("u", "inv", "c1", {"x": "cm://no_such_resource"})

    with pytest.raises(RuntimeError, match="미지원 resource"):
        asyncio.run(_main())


# ── _exec_tool_call — 직접 (요약 분기 / cm.* 주입 / bind / 실패) ─────────────


def _tool_ctx() -> dict:
    return {"__persona__": 2, "steps": {"prev": {"v": 1}}, "inputs": {}, "parent_outputs": {}}


def test_exec_tool_call_patents_and_query_summary(monkeypatch):
    cm, _rec = _install(monkeypatch)

    async def _tool(name, params, **kwargs):
        return {
            "status": "ok",
            "result": {
                "patents": [
                    {"application_number": "A1", "title": "T1" * 60},
                    {"application_number": "A2", "title": "T2"},
                    "not-a-dict",
                ],
                "query": "q" * 200,
            },
        }

    monkeypatch.setattr(O, "dispatch_tool", _tool)
    step = {"id": "t0", "tool": "kipris.search_patents", "params": {"q": "x"}}

    async def _main():
        return await O._exec_tool_call("u", "inv", "c1", step, _tool_ctx())

    out = asyncio.run(_main())
    # result unwrap → payload 반환 (bind 없음)
    assert out["patents"][0]["application_number"] == "A1"
    done = [
        c.args[4]
        for c in cm.append_trail.await_args_list
        if c.args[4].get("event") == "tool_call_done"
    ]
    summary = done[0]["summary"]
    assert summary["patents_count"] == 3  # not-a-dict 포함 길이
    assert len(summary["patents_preview"]) == 2  # dict 만 preview
    assert len(summary["query"]) == 100  # query[:100]


def test_exec_tool_call_figure_and_review_summary_with_bind(monkeypatch):
    cm, _rec = _install(monkeypatch)
    import base64

    fig = base64.b64encode(b"x" * 12).decode("ascii")

    async def _tool(name, params, **kwargs):
        # 'result' 키 없음 → resp 자체가 payload. status 도 없음.
        return {
            "figure_bytes_b64": fig,
            "chosen_tool": "plantuml",
            "review": {"overall_pass": True},
        }

    monkeypatch.setattr(O, "dispatch_tool", _tool)
    step = {"id": "t0", "tool": "drawing.render", "params": {}, "bind": "fig_out"}

    async def _main():
        return await O._exec_tool_call("u", "inv", "c1", step, _tool_ctx())

    out = asyncio.run(_main())
    # bind 있음 → {bind: payload}
    assert "fig_out" in out
    done = [
        c.args[4]
        for c in cm.append_trail.await_args_list
        if c.args[4].get("event") == "tool_call_done"
    ]
    summary = done[0]["summary"]
    assert summary["figure_bytes"] == 12  # len(b64)*3//4
    assert summary["chosen_tool"] == "plantuml"
    assert summary["overall_pass"] is True


def test_exec_tool_call_cm_prefix_injects_identity(monkeypatch):
    cm, _rec = _install(monkeypatch)
    captured_params: dict = {}

    async def _tool(name, params, **kwargs):
        captured_params.update(params)
        return {"status": "ok", "result": {}}

    monkeypatch.setattr(O, "dispatch_tool", _tool)
    step = {"id": "t0", "tool": "cm.save_drawing_artifacts", "params": {"foo": "bar"}}

    async def _main():
        return await O._exec_tool_call("u", "inv", "c1", step, _tool_ctx())

    asyncio.run(_main())
    assert captured_params["user_id"] == "u"
    assert captured_params["work_id"] == "inv"
    assert captured_params["foo"] == "bar"


def test_exec_tool_call_params_non_dict_coerced(monkeypatch):
    cm, _rec = _install(monkeypatch)
    # substitute 가 dict 아닌 값 반환 → params = {}
    monkeypatch.setattr(O, "substitute_placeholders", lambda spec, ctx: "not-a-dict")
    seen: dict = {}

    async def _tool(name, params, **kwargs):
        seen.update({"params": params})
        return {"status": "ok"}

    monkeypatch.setattr(O, "dispatch_tool", _tool)
    step = {"id": "t0", "tool": "some.tool", "params_map": {"x": "$.y"}}

    async def _main():
        return await O._exec_tool_call("u", "inv", "c1", step, _tool_ctx())

    asyncio.run(_main())
    assert seen["params"] == {}


def test_exec_tool_call_dispatch_failure_appends_trail_and_raises(monkeypatch):
    cm, _rec = _install(monkeypatch)

    async def _tool(name, params, **kwargs):
        raise RuntimeError("tool exploded")

    monkeypatch.setattr(O, "dispatch_tool", _tool)
    step = {"id": "t0", "tool": "boom.tool", "params": {}}

    async def _main():
        await O._exec_tool_call("u", "inv", "c1", step, _tool_ctx())

    with pytest.raises(RuntimeError, match="tool exploded"):
        asyncio.run(_main())
    events = [c.args[4].get("event") for c in cm.append_trail.await_args_list]
    assert "tool_call_failed" in events


def test_exec_tool_call_step_id_propagates_to_trail(monkeypatch):
    """tool=RT 통일(N-7) — tool step 은 RT 라 id 필수. step.id 가 trail step_id 로 전파."""
    cm, _rec = _install(monkeypatch)

    async def _tool(name, params, **kwargs):
        return {"status": "ok", "result": {}}

    monkeypatch.setattr(O, "dispatch_tool", _tool)
    step = {"id": "t7", "tool": "no.id.tool", "params": {}}

    async def _main():
        return await O._exec_tool_call("u", "inv", "c1", step, _tool_ctx())

    asyncio.run(_main())
    started = [
        c.args[4]
        for c in cm.append_trail.await_args_list
        if c.args[4].get("event") == "tool_call_started"
    ]
    assert started[0]["step_id"] == "t7"


def test_exec_tool_call_maturity_no_model_raw(monkeypatch):
    """maturity.compute tool 은 CM PUT 부수효과만 — DRO 는 model RAW(maturity_updated) **미발사**.
    (#12: model.maturity WS 는 Nexus 가 chain_completed 수신 시 CM fetch 로 생성.)"""
    cm, rec = _install(monkeypatch)

    async def _tool(name, params, **kwargs):
        return {"status": "ok", "result": {"overall_score": 0.5, "scores": {}}}

    monkeypatch.setattr(O, "dispatch_tool", _tool)
    step = {"id": "m", "tool": "maturity.compute", "params": {}}

    async def _main():
        return await O._exec_tool_call("u", "inv", "c1", step, _tool_ctx())

    out = asyncio.run(_main())
    assert out == {"overall_score": 0.5, "scores": {}}
    assert rec.of_type("maturity_updated") == []  # #12 — DRO 미발사 (음성검증)


def test_exec_tool_call_roadmap_no_model_raw(monkeypatch):
    """roadmap.persist tool 은 CM PUT 부수효과만 — DRO 는 model RAW(roadmap_updated) **미발사** (#12)."""
    cm, rec = _install(monkeypatch)

    async def _tool(name, params, **kwargs):
        return {"status": "ok", "result": {"count": 2}}

    monkeypatch.setattr(O, "dispatch_tool", _tool)
    step = {"id": "r", "tool": "roadmap.persist", "params": {}}

    async def _main():
        return await O._exec_tool_call("u", "inv", "c1", step, _tool_ctx())

    out = asyncio.run(_main())
    assert out == {"count": 2}
    assert rec.of_type("roadmap_updated") == []  # #12 — DRO 미발사 (음성검증)


def test_exec_tool_call_release_failure_swallowed(monkeypatch):
    """tool RT 성공 후 lease 해제 실패는 swallow (N-7, _dispatch_rt 와 동형)."""
    cm, _rec = _install(monkeypatch)
    cm.persona_queue_release.side_effect = RuntimeError("rel boom")

    async def _tool(name, params, **kwargs):
        return {"status": "ok", "result": {"x": 1}}

    monkeypatch.setattr(O, "dispatch_tool", _tool)
    step = {"id": "t0", "tool": "t.x", "params": {}}

    async def _main():
        return await O._exec_tool_call("u", "inv", "c1", step, _tool_ctx())

    assert asyncio.run(_main()) == {"x": 1}  # 해제 실패에도 정상 반환


def test_exec_tool_call_dispatch_failure_release_failure_both_swallowed(monkeypatch):
    """tool RT dispatch 실패 + lease 해제도 실패 → 둘 다 swallow 후 원 예외 raise (N-7)."""
    cm, _rec = _install(monkeypatch)
    cm.persona_queue_release.side_effect = RuntimeError("rel boom")

    async def _tool(name, params, **kwargs):
        raise RuntimeError("tool boom")

    monkeypatch.setattr(O, "dispatch_tool", _tool)
    step = {"id": "t0", "tool": "t.x", "params": {}}

    async def _main():
        await O._exec_tool_call("u", "inv", "c1", step, _tool_ctx())

    with pytest.raises(RuntimeError, match="tool boom"):
        asyncio.run(_main())
