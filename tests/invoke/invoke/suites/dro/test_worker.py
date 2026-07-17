"""200.DRO worker — 이벤트 구동 chain 구동 (C1, invoke 단위).

대상: 200.DRO/src/worker.py (run_chain facade · _drive_chain · _worker_loop · 레지스터).
구 orchestrator.progress_chain/spawn_chain 테스트가 worker 로 이전 + worker 모델 신규.

전략 (test_orchestrator 동형):
  - get_cm_client       → AsyncMock CMClient. **W·O 양쪽** patch (_drive_chain 이 O._run_steps 호출).
  - event_sse.emit_raw  → _EmitRecorder. event_sse 는 공유 모듈이라 한 번 patch 로 W·O 둘 다 적용.
  - load_pipeline/resolve_dispatch → W.* patch (worker 가 호출). dispatch_with_retry/dispatch_tool → O.* (O._run_steps 경유).
  - ensure_worker       → run_chain facade 테스트는 fake 로 (실 worker task 안 띄움).
async 는 asyncio.run(...) 로.
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
import src.worker as W  # noqa: E402


# ── 공통 fakes ──────────────────────────────────────────────────────────────


class _EmitRecorder:
    def __init__(self) -> None:
        self.emits: list[tuple[str, str, str, dict]] = []
        self.meta: list[dict] = []

    async def __call__(self, user_id, work_id, event_type, payload, *, persona=None, step=None):
        self.emits.append((user_id, work_id, event_type, payload))
        self.meta.append({"persona": persona, "step": step})

    def of_type(self, t: str) -> list[tuple]:
        return [e for e in self.emits if e[2] == t]


def _make_cm() -> AsyncMock:
    cm = AsyncMock()
    cm.persona_queue_pop.return_value = {"empty": True}
    cm.create_chain.return_value = {"ok": True}
    cm.create_rt.return_value = {"ok": True}
    cm.patch_rt.return_value = {"ok": True}
    cm.patch_chain.return_value = {"ok": True}
    cm.persona_queue_push.return_value = {"ok": True}
    cm.append_trail.return_value = None
    cm.get_persona_queue.return_value = {"pending": [], "leases": {}}
    return cm


def _install(monkeypatch, *, cm=None) -> tuple[AsyncMock, _EmitRecorder]:
    """worker 의외부 의존 fake 교체. get_cm_client 는 W·O 둘 다 (drive_chain 이 O._run_steps 호출).
    emit_raw 는 공유 event_sse 모듈 attribute → 한 번 patch 로 W·O 둘 다 적용."""
    cm = cm or _make_cm()
    rec = _EmitRecorder()
    monkeypatch.setattr(W, "get_cm_client", lambda: cm)
    monkeypatch.setattr(O, "get_cm_client", lambda: cm)
    monkeypatch.setattr(O.event_sse, "emit_raw", rec)
    monkeypatch.setattr(O, "substitute_placeholders", lambda spec, ctx: spec)
    return cm, rec


def _llm_pipeline(pid="P02.R00.X", persona=2, dispatch_to=None) -> dict:
    return {
        "pipeline_id": pid,
        "persona": persona,
        "llm": "claude-opus-4-7",
        "llm_fallback": None,
        "dispatch_to": dispatch_to,
        "steps": [{"id": "s0", "instructions": {"inline": "do"}, "output_contract": None}],
    }


def _tool_pipeline(tool: str, *, last_in_list=False) -> dict:
    step = {"id": "t0", "tool": tool, "params": {"q": "x"}}
    steps = [[step]] if last_in_list else [step]
    return {
        "pipeline_id": "P02.R00.T",
        "persona": 2,
        "llm": None,
        "llm_fallback": None,
        "dispatch_to": None,
        "steps": steps,
    }


# ── run_chain facade (구 spawn_chain) ─────────────────────────────────────────


def test_run_chain_creates_chain_and_produces(monkeypatch):
    """run_chain = chain 생성 + producer pre-push(_enqueue_all_rts) + ensure_worker + wake.set()."""
    cm, _rec = _install(monkeypatch)
    monkeypatch.setattr(W, "resolve_pipeline_id", lambda p: p)
    monkeypatch.setattr(
        W, "load_pipeline", lambda p: {"pipeline_id": "P01.R00.X", "persona": 1, "steps": []}
    )
    ensured: list[tuple] = []
    fw = W._Worker(wake=asyncio.Event())

    async def _ensure(u, w, p):
        ensured.append((u, w, p))
        return fw

    monkeypatch.setattr(W, "ensure_worker", _ensure)

    async def _main():
        return await W.run_chain(
            "u", "inv", "P01.R00.X", persona=1, chain_id="c1", trigger={"kind": "user_message"}
        )

    out = asyncio.run(_main())
    assert out == "c1"
    cm.create_chain.assert_awaited_once_with(
        "u", "inv", "c1", "P01.R00.X", 1, {"kind": "user_message"}
    )
    assert ensured == [("u", "inv", 1)]
    assert fw.wake.is_set()  # enqueue 후 깨움 (RAW 순서: rt_enqueued < rt_started)


def test_run_chain_facade_resolves_and_generates_chain_id(monkeypatch):
    """short-form pid resolve + chain_id 미지정 시 생성 + persona pipeline 에서 도출."""
    cm, _rec = _install(monkeypatch)
    monkeypatch.setattr(W, "resolve_pipeline_id", lambda p: p + ".FULL")
    monkeypatch.setattr(W, "load_pipeline", lambda p: {"pipeline_id": p, "persona": 3, "steps": []})
    fw = W._Worker(wake=asyncio.Event())
    monkeypatch.setattr(W, "ensure_worker", AsyncMock(return_value=fw))

    async def _main():
        return await W.run_chain("u", "inv", "P03.R00", trigger={"kind": "x"})

    cid = asyncio.run(_main())
    assert isinstance(cid, str) and cid  # 생성됨
    # full id + persona(pipeline 도출) 로 create_chain
    args = cm.create_chain.await_args.args
    assert args[3] == "P03.R00.FULL"
    assert args[4] == 3


def test_run_chain_invalid_persona_raises(monkeypatch):
    _install(monkeypatch)
    monkeypatch.setattr(W, "resolve_pipeline_id", lambda p: p)
    monkeypatch.setattr(W, "load_pipeline", lambda p: {"pipeline_id": p, "persona": 0, "steps": []})

    async def _main():
        await W.run_chain("u", "inv", "PX", persona=None, trigger={})

    with pytest.raises(RuntimeError, match="persona 미해결"):
        asyncio.run(_main())


# ── _drive_chain — persona mismatch (구 progress_chain) ───────────────────────


def test_drive_chain_persona_mismatch_marks_failed(monkeypatch):
    """A-5 — 초기구간(persona mismatch) 실패도 chain=failed + 내부 error RAW (구 raise/silent 제거)."""
    cm, rec = _install(monkeypatch)
    cm.get_chain.return_value = {"pipeline_id": "P01.R00.X", "persona": 1, "trigger": {}}
    monkeypatch.setattr(
        W, "load_pipeline", lambda pid: {"pipeline_id": "P01.R00.X", "persona": 2, "steps": []}
    )

    async def _main():
        await W._drive_chain("u", "inv", 1, "c1")

    asyncio.run(_main())  # raise 안 함 — outer except 가 처리
    statuses = [c.args[4].get("status") for c in cm.patch_chain.await_args_list]
    assert statuses[-1] == "failed"
    errs = rec.of_type("error")
    assert errs and "persona mismatch" in errs[0][3]["message"]


# ── _drive_chain — LLM step success ──────────────────────────────────────────


def test_drive_chain_llm_step_success_no_dispatch(monkeypatch):
    cm, rec = _install(monkeypatch)
    cm.get_chain.return_value = {"pipeline_id": "P02.R00.X", "persona": 2, "trigger": {}}
    monkeypatch.setattr(W, "load_pipeline", lambda pid: _llm_pipeline())
    cm.get_rt.return_value = {
        "rt_id": "rt0",
        "step_id": "s0",
        "input": {"k": "v"},
        "state": "pending",
    }

    async def _dispatch(persona, chain_id, rt_id, user_id, work_id, on_event=None):
        await on_event({"type": "progress", "data": {"phase": "llm"}})
        return {"text": "hi", "structured": {"key": "val"}}

    monkeypatch.setattr(O, "dispatch_with_retry", _dispatch)

    async def _main():
        await W._drive_chain("u", "inv", 2, "c1")

    asyncio.run(_main())
    statuses = [c.args[4].get("status") for c in cm.patch_chain.await_args_list]
    assert statuses == ["active", "done"]
    assert any(e[2] == "chain_completed" for e in rec.emits)
    done_patches = [
        c.args[5] for c in cm.patch_rt.await_args_list if c.args[5].get("state") == "done"
    ]
    assert done_patches
    assert done_patches[0]["output"] == {"text": "hi", "structured": {"key": "val"}}


# ── _drive_chain — dispatch_to handoff (구 spawn_chain → run_chain) ───────────


def test_drive_chain_dispatch_to_hands_off_next_chain(monkeypatch):
    cm, _rec = _install(monkeypatch)
    cm.get_chain.return_value = {
        "pipeline_id": "P02.R00.X",
        "persona": 2,
        "trigger": {"ancestor_pipeline_ids": ["P00.PRE"]},
    }
    pipe = _llm_pipeline(dispatch_to={"actions": [["P03.R00.NEXT"]]})

    def _load(pid):
        if pid == "P03.R00.NEXT":
            return {"pipeline_id": "P03.R00.NEXT", "persona": 3, "steps": []}
        return pipe

    monkeypatch.setattr(W, "load_pipeline", _load)
    cm.get_rt.return_value = {"rt_id": "rt0", "step_id": "s0", "input": {}, "state": "pending"}
    monkeypatch.setattr(W, "resolve_dispatch", lambda **k: ["P03.R00.NEXT"])

    async def _dispatch(*a, on_event=None, **k):
        return {"dispatch_choice": 0}

    monkeypatch.setattr(O, "dispatch_with_retry", _dispatch)

    handed: list[tuple] = []

    async def _run_chain(
        user_id, work_id, pipeline_id, *, persona=None, chain_id=None, trigger=None
    ):
        handed.append((pipeline_id, persona, trigger))
        return chain_id

    monkeypatch.setattr(W, "run_chain", _run_chain)

    async def _main():
        await W._drive_chain("u", "inv", 2, "c1")

    asyncio.run(_main())
    assert len(handed) == 1
    next_pid, next_persona, trigger = handed[0]
    assert next_pid == "P03.R00.NEXT"
    assert next_persona == 3
    assert trigger["ancestor_pipeline_ids"] == ["P00.PRE", "P02.R00.X"]
    assert trigger["spawned_from"] == "c1"
    events = [c.args[4].get("event") for c in cm.append_trail.await_args_list]
    assert "chain_dispatched" in events


def test_drive_chain_dispatch_next_invalid_persona_fails(monkeypatch):
    cm, _rec = _install(monkeypatch)
    cm.get_chain.return_value = {"pipeline_id": "P02.R00.X", "persona": 2, "trigger": {}}
    pipe = _llm_pipeline(dispatch_to={"actions": [["P99.R00.BAD"]]})

    def _load(pid):
        if pid == "P99.R00.BAD":
            return {"pipeline_id": "P99.R00.BAD", "persona": 0, "steps": []}
        return pipe

    monkeypatch.setattr(W, "load_pipeline", _load)
    cm.get_rt.return_value = {"rt_id": "rt0", "step_id": "s0", "input": {}, "state": "pending"}
    monkeypatch.setattr(W, "resolve_dispatch", lambda **k: ["P99.R00.BAD"])
    monkeypatch.setattr(O, "dispatch_with_retry", AsyncMock(return_value={}))

    async def _main():
        await W._drive_chain("u", "inv", 2, "c1")

    asyncio.run(_main())
    statuses = [c.args[4].get("status") for c in cm.patch_chain.await_args_list]
    assert statuses[-1] == "failed"


def test_drive_chain_dispatch_resolve_failure_marks_failed(monkeypatch):
    """A-6 — dispatch resolve 실패의 done 위장 제거: chain_dispatch_failed trail + chain=failed."""
    cm, rec = _install(monkeypatch)
    cm.get_chain.return_value = {"pipeline_id": "P02.R00.X", "persona": 2, "trigger": {}}
    pipe = _llm_pipeline(dispatch_to={"actions": [["P03.R00.NEXT"]]})
    monkeypatch.setattr(W, "load_pipeline", lambda pid: pipe)
    cm.get_rt.return_value = {"rt_id": "rt0", "step_id": "s0", "input": {}, "state": "pending"}

    def _boom(**k):
        raise RuntimeError("resolve kaboom")

    monkeypatch.setattr(W, "resolve_dispatch", _boom)
    monkeypatch.setattr(O, "dispatch_with_retry", AsyncMock(return_value={}))

    async def _main():
        await W._drive_chain("u", "inv", 2, "c1")

    asyncio.run(_main())  # raise 안 함 — outer except 가 처리
    events = [c.args[4].get("event") for c in cm.append_trail.await_args_list]
    assert "chain_dispatch_failed" in events
    assert "chain_completed" not in events  # done 위장 제거 (성공 신호 안 나감)
    statuses = [c.args[4].get("status") for c in cm.patch_chain.await_args_list]
    assert statuses[-1] == "failed"
    assert rec.of_type("error")  # 내부 error 신호 발사
    assert not rec.of_type("chain_completed")


# ── _drive_chain — tool step ─────────────────────────────────────────────────


def test_drive_chain_tool_step_maturity_no_model_raw(monkeypatch):
    """maturity.compute tool step — CM PUT 부수효과·tool_call_done·chain done 은 유지,
    DRO 는 model RAW(maturity_updated) **미발사** (#12: model.maturity 는 Nexus 가 CM fetch 로 생성)."""
    cm, rec = _install(monkeypatch)
    cm.get_chain.return_value = {"pipeline_id": "P02.R00.T", "persona": 2, "trigger": {}}
    monkeypatch.setattr(W, "load_pipeline", lambda pid: _tool_pipeline("maturity.compute"))

    async def _tool(name, params, **kwargs):
        assert params["user_id"] == "u"
        return {
            "status": "ok",
            "result": {"overall_score": 0.7, "scores": {"clarity": 0.5}, "weights": {"c": 1}},
        }

    monkeypatch.setattr(O, "dispatch_tool", _tool)

    async def _main():
        await W._drive_chain("u", "inv", 2, "c1")

    asyncio.run(_main())
    assert rec.of_type("maturity_updated") == []  # #12 — DRO 미발사 (음성검증)
    events = [c.args[4].get("event") for c in cm.append_trail.await_args_list]
    assert "tool_call_done" in events
    statuses = [c.args[4].get("status") for c in cm.patch_chain.await_args_list]
    assert statuses[-1] == "done"


def test_drive_chain_tool_step_roadmap_no_model_raw_nested_parallel(monkeypatch):
    """roadmap.persist tool step (nested parallel) — parallel_started/done 트레일은 유지,
    DRO 는 model RAW(roadmap_updated) **미발사** (#12: model.roadmap 은 Nexus 가 CM fetch 로 생성)."""
    cm, rec = _install(monkeypatch)
    cm.get_chain.return_value = {"pipeline_id": "P02.R00.T", "persona": 2, "trigger": {}}
    monkeypatch.setattr(
        W, "load_pipeline", lambda pid: _tool_pipeline("roadmap.persist", last_in_list=True)
    )
    monkeypatch.setattr(
        O, "dispatch_tool", AsyncMock(return_value={"status": "ok", "result": {"count": 5}})
    )

    async def _main():
        await W._drive_chain("u", "inv", 2, "c1")

    asyncio.run(_main())
    assert rec.of_type("roadmap_updated") == []  # #12 — DRO 미발사 (음성검증)
    events = [c.args[4].get("event") for c in cm.append_trail.await_args_list]
    assert "parallel_started" in events
    assert "parallel_done" in events


# ── worker 레지스터 / 루프 (신규) ─────────────────────────────────────────────


def test_ensure_worker_lazy_creates_once(monkeypatch):
    """같은 (session,persona) 두 번 ensure → task 1개 (idempotent)."""
    _install(monkeypatch)
    W._WORKERS.clear()
    # worker loop 가 즉시 idle-stop 하게 큐 항상 empty + grace 0.
    monkeypatch.setattr(W, "_IDLE_GRACE_S", 0.0)

    async def _main():
        w1 = await W.ensure_worker("u", "inv", 2)
        w2 = await W.ensure_worker("u", "inv", 2)
        same = w1 is w2 or (w1.task is w2.task)
        await W.shutdown_all()
        return same

    assert asyncio.run(_main())


def test_worker_loop_drives_then_idle_stops(monkeypatch):
    """worker 가 pending chain 을 구동(_drive_chain)한 뒤 큐 비면 idle 종료 + 레지스터 제거."""
    cm, _rec = _install(monkeypatch)
    W._WORKERS.clear()
    monkeypatch.setattr(W, "_IDLE_GRACE_S", 0.01)
    # get_persona_queue: 첫 호출 chain c1, 이후 empty.
    calls = {"n": 0}

    async def _queue(u, w, p):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"pending": [{"rt_id": "r", "chain_id": "c1"}], "leases": {}}
        return {"pending": [], "leases": {}}

    cm.get_persona_queue.side_effect = _queue
    cm.persona_queue_pop.return_value = {"empty": True}  # drain no-op
    driven: list[str] = []

    async def _drive(u, w, p, cid):
        driven.append(cid)

    monkeypatch.setattr(W, "_drive_chain", _drive)

    async def _main():
        w = await W.ensure_worker("u", "inv", 2)
        # worker task 가 c1 구동 후 idle-stop 할 때까지 대기.
        for _ in range(200):
            await asyncio.sleep(0.01)
            if w.task.done():
                break
        return w

    w = asyncio.run(_main())
    assert driven == ["c1"]
    assert w.task.done()
    assert ("u", "inv", 2) not in W._WORKERS  # idle-stop 시 제거


def test_shutdown_all_cancels_workers(monkeypatch):
    _install(monkeypatch)
    W._WORKERS.clear()
    monkeypatch.setattr(W, "_IDLE_GRACE_S", 100.0)  # idle 안 끝나게 (cancel 로만 종료)

    async def _main():
        w = await W.ensure_worker("u", "inv", 2)
        await asyncio.sleep(0.02)  # worker 가 wake 대기에 들어가게
        await W.shutdown_all()
        return w

    w = asyncio.run(_main())
    assert w.task.done()
    assert not W._WORKERS


# ── _drain_chain_pending / worker 루프 edge (잔여·예외·cancel·race) ────────────


def test_drain_chain_pending_releases_residual_rts(monkeypatch):
    """초기구간/step 실패로 큐에 남은 RT 를 pop+release (worker 가 같은 chain 무한 재선택 방지)."""
    cm, _rec = _install(monkeypatch)
    cm.persona_queue_pop.side_effect = [
        {"rt_id": "r1", "chain_id": "c1"},
        {"rt_id": "r2", "chain_id": "c1"},
        {"empty": True},
    ]

    async def _main():
        await W._drain_chain_pending(cm, "u", "inv", 2, "c1")

    asyncio.run(_main())
    released = [c.args[3] for c in cm.persona_queue_release.await_args_list]
    assert released == ["r1", "r2"]
    assert all(c.kwargs.get("chain_id") == "c1" for c in cm.persona_queue_pop.await_args_list)


def test_worker_loop_drive_exception_logged_and_continues(monkeypatch):
    """_drive_chain 의 (초기구간) 예외가 worker·타 chain 을 안 죽임 — 로그 후 finally drain + idle-stop."""
    cm, _rec = _install(monkeypatch)
    W._WORKERS.clear()
    monkeypatch.setattr(W, "_IDLE_GRACE_S", 0.01)
    calls = {"n": 0}

    async def _queue(u, w, p):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"pending": [{"rt_id": "r", "chain_id": "c1"}], "leases": {}}
        return {"pending": [], "leases": {}}

    cm.get_persona_queue.side_effect = _queue
    cm.persona_queue_pop.return_value = {"empty": True}

    async def _boom(u, w, p, cid):
        raise RuntimeError("drive kaboom")

    monkeypatch.setattr(W, "_drive_chain", _boom)

    async def _main():
        w = await W.ensure_worker("u", "inv", 2)
        for _ in range(300):
            await asyncio.sleep(0.005)
            if w.task.done():
                break
        return w

    w = asyncio.run(_main())
    assert w.task.done()  # 예외에도 정상 idle-stop (죽지 않음)
    assert ("u", "inv", 2) not in W._WORKERS
    assert any(c.kwargs.get("chain_id") == "c1" for c in cm.persona_queue_pop.await_args_list)


def test_worker_loop_cancel_during_drive_reraises(monkeypatch):
    """drive 중 shutdown cancel → CancelledError 가 except Exception 에 안 먹히고 재raise (worker 종료)."""
    cm, _rec = _install(monkeypatch)
    W._WORKERS.clear()
    monkeypatch.setattr(W, "_IDLE_GRACE_S", 100.0)
    cm.get_persona_queue.return_value = {
        "pending": [{"rt_id": "r", "chain_id": "c1"}],
        "leases": {},
    }
    cm.persona_queue_pop.return_value = {"empty": True}
    entered = asyncio.Event()

    async def _drive(u, w, p, cid):
        entered.set()
        await asyncio.sleep(100)  # cancel 을 여기서 수신

    monkeypatch.setattr(W, "_drive_chain", _drive)

    async def _main():
        w = await W.ensure_worker("u", "inv", 2)
        await asyncio.wait_for(entered.wait(), timeout=2)  # drive 진입 보장
        await W.shutdown_all()
        return w

    w = asyncio.run(_main())
    assert w.task.done()
    assert not W._WORKERS


def test_worker_loop_push_during_clear_continues(monkeypatch):
    """wake.clear 직후 producer push (race) → 141 재검 not-None → continue (idle 안 들어감)."""
    cm, _rec = _install(monkeypatch)
    W._WORKERS.clear()
    monkeypatch.setattr(W, "_IDLE_GRACE_S", 0.01)
    pend = {"pending": [{"rt_id": "r", "chain_id": "c1"}], "leases": {}}
    empty = {"pending": [], "leases": {}}
    seq = [empty, pend, pend, empty, empty]  # 124,141(race),124(drive),124,141
    calls = {"n": 0}

    async def _queue(u, w, p):
        i = calls["n"]
        calls["n"] += 1
        return seq[i] if i < len(seq) else empty

    cm.get_persona_queue.side_effect = _queue
    cm.persona_queue_pop.return_value = {"empty": True}
    driven: list[str] = []

    async def _drive(u, w, p, cid):
        driven.append(cid)

    monkeypatch.setattr(W, "_drive_chain", _drive)

    async def _main():
        w = await W.ensure_worker("u", "inv", 2)
        for _ in range(300):
            await asyncio.sleep(0.005)
            if w.task.done():
                break
        return w

    w = asyncio.run(_main())
    assert driven == ["c1"]  # race 후 정상 구동
    assert w.task.done()


def test_worker_loop_woken_from_idle_drives_next(monkeypatch):
    """idle wait 중 producer wake.set → wait_for 반환(timeout 아님) → 145 continue → 다음 chain 구동."""
    cm, _rec = _install(monkeypatch)
    W._WORKERS.clear()
    monkeypatch.setattr(W, "_IDLE_GRACE_S", 100.0)  # timeout 안 나게 — wake 로만
    state = {"armed": False}

    async def _queue(u, w, p):
        if state["armed"]:
            state["armed"] = False
            return {"pending": [{"rt_id": "r", "chain_id": "c1"}], "leases": {}}
        return {"pending": [], "leases": {}}

    cm.get_persona_queue.side_effect = _queue
    cm.persona_queue_pop.return_value = {"empty": True}
    driven: list[str] = []

    async def _drive(u, w, p, cid):
        driven.append(cid)

    monkeypatch.setattr(W, "_drive_chain", _drive)

    async def _main():
        w = await W.ensure_worker("u", "inv", 2)
        await asyncio.sleep(0.05)  # worker 가 idle wait_for 진입
        state["armed"] = True
        w.wake.set()  # idle wait 깨움 (145 continue)
        for _ in range(200):
            await asyncio.sleep(0.01)
            if driven:
                break
        await W.shutdown_all()
        return driven

    assert asyncio.run(_main()) == ["c1"]


def test_worker_loop_wake_during_teardown_continues(monkeypatch):
    """idle timeout 후 레지스터 lock 진입 직전 producer wake → 149 is_set True → 150 continue (제거 취소)."""
    cm, _rec = _install(monkeypatch)
    W._WORKERS.clear()
    monkeypatch.setattr(W, "_IDLE_GRACE_S", 0.01)  # 빠른 timeout → teardown 창
    state = {"armed": False}

    async def _queue(u, w, p):
        if state["armed"]:
            state["armed"] = False
            return {"pending": [{"rt_id": "r", "chain_id": "c1"}], "leases": {}}
        return {"pending": [], "leases": {}}

    cm.get_persona_queue.side_effect = _queue
    cm.persona_queue_pop.return_value = {"empty": True}
    driven: list[str] = []

    async def _drive(u, w, p, cid):
        driven.append(cid)

    monkeypatch.setattr(W, "_drive_chain", _drive)

    async def _main():
        # 레지스터 lock 을 먼저 점유해 worker 의 teardown(148 acquire)을 막는다.
        # (ensure_worker 도 같은 lock → deadlock 회피 위해 task 직접 생성.)
        async with W._REGISTRY_LOCK:
            w = W._Worker(wake=asyncio.Event())
            w.task = asyncio.create_task(W._worker_loop("u", "inv", 2, w))
            W._WORKERS[("u", "inv", 2)] = w
            await asyncio.sleep(0.1)  # worker: 143 timeout → 148 lock 대기(우리가 점유)
            state["armed"] = True
            w.wake.set()  # teardown 창에서 깨움 → 149 is_set True → 150 continue
        # lock 해제 → worker lock 획득 → wake set 봄 → 150 continue → 124 armed → c1 구동.
        for _ in range(200):
            await asyncio.sleep(0.01)
            if driven:
                break
        await W.shutdown_all()
        return driven

    assert asyncio.run(_main()) == ["c1"]  # teardown 취소 후 정상 구동


# ── A-3 재시작 자동복구 (resume_active_chains · rehydrate · resume drive) ──────


def test_resume_active_chains_registers_and_wakes(monkeypatch):
    """전 세션 미완 chain 을 각 worker resume 에 등록 + 깨움. persona 결손 entry 는 skip."""
    cm, _rec = _install(monkeypatch)
    cm.list_active_chains.return_value = [
        {"user_id": "u", "work_id": "inv", "persona": 2, "chain_id": "c1"},
        {"user_id": "u", "work_id": "inv", "persona": 2, "chain_id": "c2"},
        {"user_id": "u", "work_id": "inv", "persona": None, "chain_id": "bad"},  # skip
        {"user_id": "u", "work_id": "inv", "persona": 2},  # chain_id 결손 skip
    ]
    fw = W._Worker(wake=asyncio.Event())
    ensured: list[tuple] = []

    async def _ensure(u, w, p):
        ensured.append((u, w, p))
        return fw

    monkeypatch.setattr(W, "ensure_worker", _ensure)
    asyncio.run(W.resume_active_chains())
    assert fw.resume == {"c1", "c2"}
    assert fw.wake.is_set()
    assert ensured == [("u", "inv", 2), ("u", "inv", 2)]


def test_resume_active_chains_list_failure_swallowed(monkeypatch):
    """list_active_chains 실패는 swallow — 복구 스킵, startup 안 죽음."""
    cm, _rec = _install(monkeypatch)
    cm.list_active_chains.side_effect = RuntimeError("cm down")
    asyncio.run(W.resume_active_chains())  # 예외 안 남


def test_rehydrate_done_steps_unwraps_llm_skips_notdone(monkeypatch):
    """trail step↔rt 매핑 → done RT 만 context 복원. LLM 은 structured unwrap, 미완은 skip."""
    cm, _rec = _install(monkeypatch)
    cm.get_trail.return_value = [
        {"event": "rt_enqueued", "step_id": "s0", "rt_id": "r0"},
        {"event": "rt_enqueued", "step_id": "s1", "rt_id": "r1"},
        {"event": "chain_started"},  # 무시
    ]
    rts = {
        "r0": {"state": "done", "output": {"text": "hi", "structured": {"k": 1}}},
        "r1": {"state": "in_flight", "output": None},  # 미완 → skip(무조건 재실행)
    }

    async def _get_rt(u, w, p, c, rt_id):
        return rts[rt_id]

    cm.get_rt.side_effect = _get_rt
    context: dict = {"steps": {}}
    asyncio.run(W._rehydrate_done_steps(cm, "u", "inv", 2, "c1", context))
    assert context["steps"] == {"s0": {"k": 1}}  # LLM structured unwrap; s1 미완 skip


def test_rehydrate_done_steps_tool_asis_and_rt_error_swallowed(monkeypatch):
    """tool RT output 은 그대로(structured 없음). get_rt 실패 RT 는 건너뜀."""
    cm, _rec = _install(monkeypatch)
    cm.get_trail.return_value = [
        {"event": "rt_enqueued", "step_id": "t0", "rt_id": "rt0"},
        {"event": "rt_enqueued", "step_id": "t1", "rt_id": "rterr"},
    ]

    async def _get_rt(u, w, p, c, rt_id):
        if rt_id == "rterr":
            raise RuntimeError("404")
        return {"state": "done", "output": {"count": 5}}

    cm.get_rt.side_effect = _get_rt
    context: dict = {"steps": {}}
    asyncio.run(W._rehydrate_done_steps(cm, "u", "inv", 2, "c1", context))
    assert context["steps"] == {"t0": {"count": 5}}  # tool as-is; rterr swallow


def test_drive_chain_resume_skips_completed_step(monkeypatch):
    """resume=True → done step(rehydrate)는 dispatch 안 하고 skip, chain 정상 완료 (A-3)."""
    cm, _rec = _install(monkeypatch)
    cm.get_chain.return_value = {"pipeline_id": "P02.R00.X", "persona": 2, "trigger": {}}
    monkeypatch.setattr(W, "load_pipeline", lambda pid: _llm_pipeline())  # 1 LLM step id s0
    cm.get_trail.return_value = [{"event": "rt_enqueued", "step_id": "s0", "rt_id": "r0"}]
    cm.get_rt.return_value = {"state": "done", "output": {"structured": {"done": True}}}
    dispatched: list = []

    async def _dispatch(*a, on_event=None, **k):
        dispatched.append(1)
        return {"text": "x"}

    monkeypatch.setattr(O, "dispatch_with_retry", _dispatch)

    async def _main():
        await W._drive_chain("u", "inv", 2, "c1", resume=True)

    asyncio.run(_main())
    assert dispatched == []  # s0 rehydrated done → skip
    statuses = [c.args[4].get("status") for c in cm.patch_chain.await_args_list]
    assert statuses[-1] == "done"


def test_worker_loop_drives_resume_chain_with_flag(monkeypatch):
    """worker loop 가 resume 등록 chain 을 resume=True 로 우선 구동."""
    cm, _rec = _install(monkeypatch)
    W._WORKERS.clear()
    monkeypatch.setattr(W, "_IDLE_GRACE_S", 0.01)
    cm.get_persona_queue.return_value = {"pending": [], "leases": {}}
    cm.persona_queue_pop.return_value = {"empty": True}
    driven: list = []

    async def _drive(u, w, p, cid, *, resume=False):
        driven.append((cid, resume))

    monkeypatch.setattr(W, "_drive_chain", _drive)

    async def _main():
        w = await W.ensure_worker("u", "inv", 2)
        w.resume.add("cR")
        w.wake.set()
        for _ in range(300):
            await asyncio.sleep(0.005)
            if driven and w.task.done():
                break
        return w

    w = asyncio.run(_main())
    assert ("cR", True) in driven
    assert w.task.done()


def test_worker_loop_resume_drive_failure_logged_continues(monkeypatch):
    """resume chain 구동 예외도 worker 를 안 죽임 — 로그 후 finally drain + idle-stop."""
    cm, _rec = _install(monkeypatch)
    W._WORKERS.clear()
    monkeypatch.setattr(W, "_IDLE_GRACE_S", 0.01)
    cm.get_persona_queue.return_value = {"pending": [], "leases": {}}
    cm.persona_queue_pop.return_value = {"empty": True}

    async def _boom(u, w, p, cid, *, resume=False):
        raise RuntimeError("resume boom")

    monkeypatch.setattr(W, "_drive_chain", _boom)

    async def _main():
        w = await W.ensure_worker("u", "inv", 2)
        w.resume.add("cR")
        w.wake.set()
        for _ in range(300):
            await asyncio.sleep(0.005)
            if w.task.done():
                break
        return w

    w = asyncio.run(_main())
    assert w.task.done()  # 예외에도 정상 idle-stop
    assert ("u", "inv", 2) not in W._WORKERS


def test_worker_loop_cancel_during_resume_reraises(monkeypatch):
    """resume 구동 중 shutdown cancel → CancelledError 재raise (worker 종료)."""
    cm, _rec = _install(monkeypatch)
    W._WORKERS.clear()
    monkeypatch.setattr(W, "_IDLE_GRACE_S", 100.0)
    cm.get_persona_queue.return_value = {"pending": [], "leases": {}}
    cm.persona_queue_pop.return_value = {"empty": True}
    entered = asyncio.Event()

    async def _drive(u, w, p, cid, *, resume=False):
        entered.set()
        await asyncio.sleep(100)

    monkeypatch.setattr(W, "_drive_chain", _drive)

    async def _main():
        w = await W.ensure_worker("u", "inv", 2)
        w.resume.add("cR")
        w.wake.set()
        await asyncio.wait_for(entered.wait(), timeout=2)
        await W.shutdown_all()
        return w

    w = asyncio.run(_main())
    assert w.task.done()
    assert not W._WORKERS


# ── C3 admission 코얼레싱 (D-1 — 4-tuple 완전대기 dedup) ───────────────────────


def test_find_pending_duplicate_matches_only_pending_same_tuple(monkeypatch):
    cm, _rec = _install(monkeypatch)
    cm.get_chains.return_value = [
        {
            "chain_id": "a",
            "persona": 2,
            "pipeline_id": "P02.R00.X",
            "status": "active",
        },  # active→no
        {
            "chain_id": "b",
            "persona": 3,
            "pipeline_id": "P02.R00.X",
            "status": "pending",
        },  # persona→no
        {"chain_id": "c", "persona": 2, "pipeline_id": "P03.R00.Y", "status": "pending"},  # pid→no
        {"chain_id": "d", "persona": 2, "pipeline_id": "P02.R00.X", "status": "pending"},  # match
    ]
    out = asyncio.run(W._find_pending_duplicate(cm, "u", "inv", 2, "P02.R00.X"))
    assert out == "d"


def test_find_pending_duplicate_none(monkeypatch):
    cm, _rec = _install(monkeypatch)
    cm.get_chains.return_value = []
    assert asyncio.run(W._find_pending_duplicate(cm, "u", "inv", 2, "P02.R00.X")) is None


def test_admission_lock_same_key_idempotent():
    W._ADMISSION_LOCKS.clear()
    l1 = W._admission_lock("u", "inv", 2)
    l2 = W._admission_lock("u", "inv", 2)
    l3 = W._admission_lock("u", "inv", 3)
    assert l1 is l2  # 같은 (session,persona) = 같은 잠금
    assert l1 is not l3  # 다른 persona = 다른 잠금


def test_run_chain_dedup_drops_pending_duplicate(monkeypatch):
    """완전 대기(pending) 동일 4-tuple 있으면 spawn 버림 — create 0·trail spawn_coalesced·무신호·echo."""
    cm, _rec = _install(monkeypatch)
    monkeypatch.setattr(W, "resolve_pipeline_id", lambda p: p)
    monkeypatch.setattr(W, "load_pipeline", lambda p: {"pipeline_id": p, "persona": 2, "steps": []})
    cm.get_chains.return_value = [
        {"chain_id": "existing", "persona": 2, "pipeline_id": "P02.R00.X", "status": "pending"}
    ]
    ensured: list = []
    monkeypatch.setattr(W, "ensure_worker", AsyncMock(side_effect=lambda *a: ensured.append(a)))

    async def _main():
        return await W.run_chain("u", "inv", "P02.R00.X", persona=2, chain_id="new", trigger={})

    out = asyncio.run(_main())
    assert out == "new"  # echo
    cm.create_chain.assert_not_awaited()  # 버림 — 생성 안 함
    assert not ensured  # worker 안 깨움
    coalesced = [
        c for c in cm.append_trail.await_args_list if c.args[4].get("event") == "spawn_coalesced"
    ]
    assert coalesced and coalesced[0].args[3] == "existing"  # 흡수된 기존 chain 의 trail 에


def test_run_chain_dedup_proceeds_when_only_active(monkeypatch):
    """같은 pipeline 이 active(실행중)면 pending 아님 → 진행(대기 ≤1 채움)."""
    cm, _rec = _install(monkeypatch)
    monkeypatch.setattr(W, "resolve_pipeline_id", lambda p: p)
    monkeypatch.setattr(W, "load_pipeline", lambda p: {"pipeline_id": p, "persona": 2, "steps": []})
    cm.get_chains.return_value = [
        {"chain_id": "running", "persona": 2, "pipeline_id": "P02.R00.X", "status": "active"}
    ]
    fw = W._Worker(wake=asyncio.Event())
    monkeypatch.setattr(W, "ensure_worker", AsyncMock(return_value=fw))

    async def _main():
        return await W.run_chain("u", "inv", "P02.R00.X", persona=2, chain_id="new", trigger={})

    assert asyncio.run(_main()) == "new"
    cm.create_chain.assert_awaited_once()
    assert fw.wake.is_set()


def test_run_chain_dedup_concurrent_serialized(monkeypatch):
    """동시 동일 4-tuple 2건 → admission 잠금 직렬화로 1개만 생성(둘째는 첫째 pending 보고 drop)."""
    cm, _rec = _install(monkeypatch)
    monkeypatch.setattr(W, "resolve_pipeline_id", lambda p: p)
    monkeypatch.setattr(W, "load_pipeline", lambda p: {"pipeline_id": p, "persona": 2, "steps": []})
    W._ADMISSION_LOCKS.clear()
    created: list[dict] = []

    async def _create(u, w, cid, pid, persona, trig):
        created.append(
            {"chain_id": cid, "persona": persona, "pipeline_id": pid, "status": "pending"}
        )
        return {"ok": True}

    cm.create_chain.side_effect = _create

    async def _get_chains(u, w):
        return list(created)

    cm.get_chains.side_effect = _get_chains
    monkeypatch.setattr(W, "ensure_worker", AsyncMock(return_value=W._Worker(wake=asyncio.Event())))

    async def _main():
        await asyncio.gather(
            W.run_chain("u", "inv", "P02.R00.X", persona=2, chain_id="c1", trigger={}),
            W.run_chain("u", "inv", "P02.R00.X", persona=2, chain_id="c2", trigger={}),
        )

    asyncio.run(_main())
    assert len(created) == 1  # 잠금 직렬화 → 첫째만 생성, 둘째 drop


def test_run_chain_idempotent_drops_existing_chain_id(monkeypatch):
    """caller-발급 chain_id 가 이미 존재(any status)면 재-spawn 버림 — create 0·worker 안깨움·trail spawn_duplicate_chain_id·echo (I1)."""
    cm, _rec = _install(monkeypatch)
    monkeypatch.setattr(W, "resolve_pipeline_id", lambda p: p)
    monkeypatch.setattr(W, "load_pipeline", lambda p: {"pipeline_id": p, "persona": 2, "steps": []})
    cm.get_chains.return_value = [
        {"chain_id": "dup", "persona": 2, "pipeline_id": "P02.R00.X", "status": "active"}
    ]
    ensured: list = []
    monkeypatch.setattr(W, "ensure_worker", AsyncMock(side_effect=lambda *a: ensured.append(a)))

    async def _main():
        return await W.run_chain("u", "inv", "P02.R00.X", persona=2, chain_id="dup", trigger={})

    out = asyncio.run(_main())
    assert out == "dup"  # echo
    cm.create_chain.assert_not_awaited()  # 덮어쓰기·재생성 안 함
    assert not ensured  # worker 안 깨움 (RT 재-enqueue 0)
    dups = [
        c
        for c in cm.append_trail.await_args_list
        if c.args[4].get("event") == "spawn_duplicate_chain_id"
    ]
    assert dups and dups[0].args[3] == "dup"  # 기존 chain_id 의 trail 에 감사 1줄
