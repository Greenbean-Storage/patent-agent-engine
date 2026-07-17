"""DRO 이벤트 구동 worker — chain 구동의 소유자 (C1, 레지스터 A-1=B+ · A-2 · A-4).

구 `orchestrator.spawn_chain`/`progress_chain`(체인마다 task) 대체:

- **(session, persona) 당 단일 worker** 가 그 persona 의 RT 큐를 순차 소비 → 같은 persona 의
  chain 직렬화 (한 번에 하나, chain-at-a-time). 다른 persona = 다른 worker (병렬 유지).
- **wake = asyncio.Event** (condition-variable). producer 가 RT enqueue 후 `wake.set()`.
  worker 가 깨어 CM 큐를 본다 — 인메모리 큐 없음(CM 큐가 단일 진실, 재시작 시 C2 가 재구성).
- **lazy 생성 + idle 종료**: 첫 enqueue 시 `ensure_worker` 가 생성, 큐 비고 idle grace 지나면
  레지스터 lock 안 double-check 후 자기 제거.
- **run_chain facade (A-4)**: pipeline-id resolve + persona resolve + chain_id + chain 생성 +
  producer pre-push(`_enqueue_all_rts`, 모든 rt_enqueued RAW) + worker 깨움. Nexus control root
  chain·dispatch_to 후속 둘 다 동일 경로.

RAW 이벤트 순서 보존: producer 가 `await _enqueue_all_rts`(모든 rt_enqueued) 완료 후 `wake.set()`
→ worker 의 첫 rt_started 는 wake 관측 후 → 체인의 rt_enqueued seq < rt_started seq (event_sse
hub 가 lock 으로 seq 순차 부여). 체인내 emit 경로(_dispatch_rt·_exec_tool_call 등) 무변경.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from . import event_sse
from .cm_client import get_cm_client
from .dispatch_resolver import resolve_dispatch
from .orchestrator import (
    _enqueue_all_rts,
    _now,
    _run_steps,
    build_chain_context,
)
from .pipeline_walker import load_pipeline, resolve_pipeline_id

log = logging.getLogger(__name__)

# worker 가 큐 비었을 때 idle 종료까지 기다리는 grace (이 안에 wake 오면 계속).
_IDLE_GRACE_S = 30.0


# ---------------------------------------------------------------------------
# Worker 레지스터
# ---------------------------------------------------------------------------


@dataclass
class _Worker:
    wake: asyncio.Event
    task: asyncio.Task | None = None
    # 재시작 자동복구 — resume_active_chains 가 채운 미완 chain_id 들 (A-3). loop 가 우선 구동.
    resume: set[str] = field(default_factory=set)


_WORKERS: dict[tuple[str, str, int], _Worker] = {}
# _WORKERS 변형 + lazy-create/idle-stop race 를 직렬화.
_REGISTRY_LOCK = asyncio.Lock()


async def ensure_worker(user_id: str, work_id: str, persona: int) -> _Worker:
    """그 (session, persona) 의 worker 보장 (없거나 끝났으면 생성). 반환된 _Worker 의
    `wake.set()` 으로 깨운다. producer(run_chain)의 enqueue **후** 호출."""
    key = (user_id, work_id, persona)
    async with _REGISTRY_LOCK:
        w = _WORKERS.get(key)
        if w is None or w.task is None or w.task.done():
            w = _Worker(wake=asyncio.Event())
            w.task = asyncio.create_task(
                _worker_loop(user_id, work_id, persona, w),
                name=f"dro-worker-{user_id}-{work_id}-p{persona}",
            )
            _WORKERS[key] = w
        return w


async def shutdown_all() -> None:
    """DRO shutdown — 전 worker cancel (best-effort drop; graceful 복구는 C2/A-3)."""
    async with _REGISTRY_LOCK:
        workers = list(_WORKERS.values())
        _WORKERS.clear()
    for w in workers:
        if w.task is not None:
            w.task.cancel()
    for w in workers:
        if w.task is not None:
            # CancelledError 는 BaseException — suppress(Exception) 로 안 잡힘. 명시.
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await w.task


async def resume_active_chains() -> None:
    """DRO startup 자동복구 (A-3) — CM 에서 전 세션 미완(pending/active) chain 을 찾아 각
    (session,persona) worker 에 resume 등록 + 깨움. 끊긴 작업이 유저 무활동에도 자동 완주
    (사용자 원칙 "무조건 동작"). 재시작은 드물고 멈춘 chain 도 대개 소수라 startup 1회 전역 스캔."""
    cm = get_cm_client()
    try:
        actives = await cm.list_active_chains()
    except Exception:  # noqa: BLE001
        log.exception("resume_active_chains: 목록 조회 실패 — 복구 스킵")
        return
    count = 0
    for ch in actives:
        user_id = ch.get("user_id")
        work_id = ch.get("work_id")
        chain_id = ch.get("chain_id")
        persona = ch.get("persona")
        if not (user_id and work_id and chain_id) or not isinstance(persona, int):
            continue
        w = await ensure_worker(user_id, work_id, persona)
        w.resume.add(chain_id)
        w.wake.set()
        count += 1
    if count:
        log.info("resume_active_chains: %d 개 미완 chain 재개 등록", count)


# ---------------------------------------------------------------------------
# Worker loop
# ---------------------------------------------------------------------------


async def _next_pending_chain(cm, user_id: str, work_id: str, persona: int) -> str | None:
    """persona 큐의 다음 구동 대상 chain (pending head 의 chain_id). 비면 None. 순수 GET."""
    q = await cm.get_persona_queue(user_id, work_id, persona)
    pending = q.get("pending") or []
    if not pending:
        return None
    return pending[0].get("chain_id")


async def _drain_chain_pending(cm, user_id: str, work_id: str, persona: int, chain_id: str) -> None:
    """chain 구동 종료(성공/실패/예외) 후 그 chain 의 남은 pending RT 를 큐에서 제거 —
    worker 가 같은 chain 을 무한 재선택하지 않게. 성공 시엔 _run_steps 가 이미 다 pop 했으므로
    대개 no-op; 초기구간 실패/step 실패로 잔여 RT 가 남은 경우 정리. 잔여 RT 는 **failed 마킹**
    (A-5 — pending/in_flight 박제 방지, 재시작 복구가 미완으로 오인하지 않게)."""
    while True:
        popped = await cm.persona_queue_pop(user_id, work_id, persona, chain_id=chain_id)
        if not popped or popped.get("empty") or not popped.get("rt_id"):
            return
        rt_id = popped["rt_id"]
        with contextlib.suppress(Exception):
            await cm.patch_rt(
                user_id,
                work_id,
                persona,
                chain_id,
                rt_id,
                {"state": "failed", "error": {"message": "chain aborted before dispatch"}},
            )
        with contextlib.suppress(Exception):
            await cm.persona_queue_release(user_id, work_id, persona, rt_id)


async def _worker_loop(user_id: str, work_id: str, persona: int, w: _Worker) -> None:
    cm = get_cm_client()
    key = (user_id, work_id, persona)
    while True:
        # 재시작 복구 우선 (A-3) — resume 등록 chain 을 먼저 구동 (rehydrate + 미완 step 재실행)
        resume_cid = w.resume.pop() if w.resume else None
        if resume_cid is not None:
            w.wake.clear()
            try:
                await _drive_chain(user_id, work_id, persona, resume_cid, resume=True)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("resume drive failed: %s (persona %s)", resume_cid, persona)
            finally:
                await _drain_chain_pending(cm, user_id, work_id, persona, resume_cid)
            continue
        chain_id = await _next_pending_chain(cm, user_id, work_id, persona)
        if chain_id is not None:
            w.wake.clear()
            try:
                await _drive_chain(user_id, work_id, persona, chain_id)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                # 백스톱 — _drive_chain 이 이미 모든 실패를 chain=failed + error 로 처리(A-5)하므로
                # 여기 도달 = _drive_chain 의 except 자체 실패(예: error RAW emit 중) 정도.
                # worker·타 chain 을 죽이지 않게 로그 후 다음 (drain 은 finally 가 수행).
                log.exception("drive_chain failed: %s (persona %s)", chain_id, persona)
            finally:
                await _drain_chain_pending(cm, user_id, work_id, persona, chain_id)
            continue
        # persona 큐 빔 → wake 대기 or idle 종료
        w.wake.clear()
        if w.resume or await _next_pending_chain(cm, user_id, work_id, persona) is not None:
            continue  # producer push(race) 또는 resume 등록
        try:
            await asyncio.wait_for(w.wake.wait(), timeout=_IDLE_GRACE_S)
            continue
        except TimeoutError:
            pass
        async with _REGISTRY_LOCK:
            if w.wake.is_set() or w.resume:
                continue  # teardown 창에서 producer 가 깨움 / resume 등록
            _WORKERS.pop(key, None)
            return


# ---------------------------------------------------------------------------
# Chain 구동 (구 progress_chain 본체 — worker 가 인라인 호출)
# ---------------------------------------------------------------------------


async def _rehydrate_done_steps(
    cm, user_id: str, work_id: str, persona: int, chain_id: str, context: dict[str, Any]
) -> None:
    """재시작 복구 (A-3) — trail 에서 step↔rt 매핑을 얻어 state=done 인 step 의 output 을
    `context["steps"]` 로 복원. 안 끝난 step 은 비워둠(무조건 재실행). LLM RT 는 _dispatch_llm_step
    과 동형으로 structured 를 unwrap 해 context 모양을 normal flow 와 일치시킨다."""
    trail = await cm.get_trail(user_id, work_id, persona, chain_id)
    step_to_rt: dict[str, str] = {}
    for ev in trail:
        if ev.get("event") == "rt_enqueued" and ev.get("step_id") and ev.get("rt_id"):
            step_to_rt[str(ev["step_id"])] = ev["rt_id"]
    for step_id, rt_id in step_to_rt.items():
        rt: dict[str, Any] | None = None
        with contextlib.suppress(Exception):
            rt = await cm.get_rt(user_id, work_id, persona, chain_id, rt_id)
        if rt is None or rt.get("state") != "done" or rt.get("output") is None:
            continue
        out = rt["output"]
        # LLM step: _dispatch_llm_step 가 structured 를 unwrap 해 context 에 넣음 — 동형 복원
        if isinstance(out, dict) and isinstance(out.get("structured"), dict | list):
            context["steps"][step_id] = out["structured"]
        else:
            context["steps"][step_id] = out


async def _drive_chain(
    user_id: str, work_id: str, persona: int, chain_id: str, *, resume: bool = False
) -> None:
    """한 chain 을 끝까지 구동. chain-at-a-time — 한 번에 한 chain 만 구동하므로 context 1개만
    live (worker 간 cross-chain 인메모리 상태 없음 → 재시작 시 CM 재구성 용이, A-3). 초기구간
    (get_chain/persona 검증/active patch) 포함 **모든 실패가 chain=failed + 내부 error 신호**
    (A-5 — silent 제거). 사용자 표면(자동복구·"재시도 중" 부드러운 텍스트)은 Nexus 가 번역(C4)."""
    cm = get_cm_client()
    try:
        chain = await cm.get_chain(user_id, work_id, persona, chain_id)
        pipeline = load_pipeline(chain["pipeline_id"])
        # persona consistency 검증 (인자 vs pipeline)
        pipeline_persona = int(pipeline.get("persona") or chain.get("persona") or 0)
        if pipeline_persona != persona:
            raise RuntimeError(
                f"chain {chain_id} persona mismatch — arg={persona} "
                f"pipeline={pipeline.get('persona')} chain={chain.get('persona')}"
            )

        await cm.patch_chain(
            user_id, work_id, persona, chain_id, {"status": "active", "activated_at": _now()}
        )
        await cm.append_trail(
            user_id,
            work_id,
            persona,
            chain_id,
            {"event": "chain_started", "pipeline_id": pipeline["pipeline_id"]},
        )

        trigger = chain.get("trigger") or {}
        steps_list, context, last_step_id = build_chain_context(
            user_id, work_id, chain_id, trigger, pipeline
        )
        if resume:
            # 재시작 복구 (A-3) — 완료(done) step output 을 context 로 복원 → _run_steps 가 skip,
            # 안 끝난 step 은 비워둠(무조건 재실행). context 골격은 build_chain_context 가
            # trigger+pipeline 으로 결정적 재구성, done step 만 CM 에서 채운다.
            await _rehydrate_done_steps(cm, user_id, work_id, persona, chain_id, context)

        await _run_steps(user_id, work_id, chain_id, steps_list, context)

        # dispatch_to 그래프 — 마지막 step 의 dispatch_choice 로 다음 chain 핸드오프.
        dispatch_to = pipeline.get("dispatch_to")
        if dispatch_to:
            steps_dict = context.get("steps") or {}
            last_output = steps_dict.get(last_step_id) if last_step_id else None
            ancestor_ids = (chain.get("trigger") or {}).get("ancestor_pipeline_ids") or []
            try:
                next_pids = resolve_dispatch(
                    pipeline_id=pipeline["pipeline_id"],
                    dispatch_to=dispatch_to,
                    last_step_output=last_output if isinstance(last_output, dict) else None,
                    ancestor_pipeline_ids=ancestor_ids,
                )
            except Exception as e:  # noqa: BLE001
                # A-6: dispatch resolve 실패를 done 으로 위장하지 않음 — trail 남기고 outer
                # except 로 승격 → chain=failed + error. (dispatch_choice 는 SoT output_contract
                # enum 강제 + validate stage 로 *발생 불가화* — 이 경로는 config 버그 최후 방어선.)
                await cm.append_trail(
                    user_id,
                    work_id,
                    persona,
                    chain_id,
                    {
                        "event": "chain_dispatch_failed",
                        "error": str(e),
                    },
                )
                raise
            for next_pid in next_pids:
                new_chain_id = str(uuid.uuid4())
                next_pipeline = load_pipeline(next_pid)
                next_persona = int(next_pipeline.get("persona") or 0)
                if not 1 <= next_persona <= 6:
                    raise RuntimeError(
                        f"dispatch_to '{next_pid}' 의 persona 추출 실패 "
                        f"(pipeline.persona={next_pipeline.get('persona')})"
                    )
                new_trigger = {
                    "kind": "spawned",
                    "parent_outputs": context.get("steps") or {},
                    "spawned_from": chain_id,
                    "spawned_from_pipeline_id": pipeline["pipeline_id"],
                    "ancestor_pipeline_ids": [*ancestor_ids, pipeline["pipeline_id"]],
                }
                # 후속 chain 핸드오프 — run_chain 이 그 persona 큐에 enqueue + 그 worker 깨움.
                # 인라인 실행 X: 다른 persona=다른 worker, 같은 persona=이 worker 의 다음 loop.
                # new_chain_id 는 trail chain_dispatched·play BFS 가 의존하므로 호출 전 생성.
                await run_chain(
                    user_id,
                    work_id,
                    next_pid,
                    persona=next_persona,
                    chain_id=new_chain_id,
                    trigger=new_trigger,
                )
                await cm.append_trail(
                    user_id,
                    work_id,
                    persona,
                    chain_id,
                    {
                        "event": "chain_dispatched",
                        "next_chain_id": new_chain_id,
                        "next_pipeline_id": next_pid,
                        "next_persona": next_persona,
                    },
                )

        await cm.patch_chain(
            user_id, work_id, persona, chain_id, {"status": "done", "completed_at": _now()}
        )
        await cm.append_trail(user_id, work_id, persona, chain_id, {"event": "chain_completed"})
        # Nexus 로 raw 이벤트 push (RAW only — persona→channel·매핑은 Nexus event_mapper)
        await event_sse.emit_raw(
            user_id, work_id, "chain_completed", {"chain_id": chain_id}, persona=persona
        )
    except Exception as e:  # noqa: BLE001
        # A-5: 초기구간 포함 모든 실패가 chain=failed + 내부 error 신호 (silent 제거).
        # chain manifest 패치는 best-effort (get_chain 자체가 CM 장애로 실패해도 error 는 발사).
        log.exception("chain failed: %s", chain_id)
        with contextlib.suppress(Exception):
            await cm.patch_chain(
                user_id,
                work_id,
                persona,
                chain_id,
                {"status": "failed", "completed_at": _now(), "error": {"message": str(e)}},
            )
        await event_sse.emit_raw(
            user_id,
            work_id,
            "error",
            {"chain_id": chain_id, "message": str(e)},
            persona=persona,
        )


# ---------------------------------------------------------------------------
# Admission 코얼레싱 (D-1 — 같은 4-tuple 완전대기 dedup)
# ---------------------------------------------------------------------------

# (user_id, work_id, persona) 별 admission 직렬화 잠금 — "조회→판정→생성" check-then-act race
# 차단. DRO 는 단일 프로세스·단일 이벤트루프(Dockerfile uvicorn --workers 없음)라 in-process
# 잠금이 충분. _REGISTRY_LOCK 동형 (lazy 생성).
_ADMISSION_LOCKS: dict[tuple[str, str, int], asyncio.Lock] = {}


def _admission_lock(user_id: str, work_id: str, persona: int) -> asyncio.Lock:
    key = (user_id, work_id, persona)
    lock = _ADMISSION_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _ADMISSION_LOCKS[key] = lock
    return lock


async def _find_pending_duplicate(
    cm, user_id: str, work_id: str, persona: int, pipeline_id: str
) -> str | None:
    """같은 (persona, pipeline_id) 의 **완전 대기중(status=pending)** 기존 chain_id (있으면 첫째).
    D-1 dedup — pending = worker 가 첫 작업 직전 active 로 바꾸므로 '아직 한 칸도 실행 안 함'.
    판정 자료 = 기존 chain 인덱스(get_chains — 새 CM 표면 0)."""
    chains = await cm.get_chains(user_id, work_id)
    for entry in chains:
        if (
            entry.get("persona") == persona
            and entry.get("pipeline_id") == pipeline_id
            and entry.get("status") == "pending"
        ):
            return entry.get("chain_id")
    return None


async def _chain_id_exists(cm, user_id: str, work_id: str, chain_id: str) -> bool:
    """이미 존재하는 chain_id (any status) 여부 — caller(Nexus)-발급 chain_id 의 재-spawn
    (네트워크 retry 등) 멱등 처리용. dispatch_to 후속은 매번 새 uuid 라 해당 없음.
    판정 자료 = 기존 chain 인덱스(get_chains — 새 CM 표면 0)."""
    chains = await cm.get_chains(user_id, work_id)
    return any(e.get("chain_id") == chain_id for e in chains)


# ---------------------------------------------------------------------------
# run_chain facade + producer (A-4)
# ---------------------------------------------------------------------------


async def run_chain(
    user_id: str,
    work_id: str,
    pipeline_id: str,
    *,
    persona: int | None = None,
    chain_id: str | None = None,
    trigger: dict[str, Any],
) -> str:
    """모든 chain 진입의 단일 facade(A-4) + producer. Nexus control root chain·dispatch_to 후속
    둘 다 동일 경로. 동작: pipeline-id resolve(short-form 허용) + load + persona resolve(인자
    우선, else pipeline.persona) + chain_id(인자 우선=Nexus media 선기록 Q34, else 생성) +
    CM chain 생성 + **producer pre-push**(step→RT resolve 후 persona 큐 순차 enqueue,
    `_enqueue_all_rts` 가 모든 rt_enqueued RAW) + worker 보장·깨움. worker 가 큐를 순차 소비
    (인라인 실행 X). chain_id 반환."""
    cm = get_cm_client()
    full_pid = resolve_pipeline_id(pipeline_id)
    pipeline = load_pipeline(full_pid)
    resolved = persona if persona is not None else int(pipeline.get("persona") or 0)
    if not 1 <= resolved <= 6:
        raise RuntimeError(
            f"run_chain '{full_pid}' persona 미해결 (arg={persona}, "
            f"pipeline.persona={pipeline.get('persona')})"
        )
    cid = chain_id or str(uuid.uuid4())
    # D-1 admission 코얼레싱 — 같은 4-tuple(user,work,persona,pipeline)의 완전대기(pending) chain 이
    # 있으면 이 spawn 은 버림: 대기건이 자기 차례에 최신 conversation 으로 한 번에 판단(메시지는
    # conversation append-only 라 유실 아님). → (session,persona) 당 실행중 ≤1 + 대기 ≤1.
    # 조회→판정→생성을 admission 잠금으로 감싸 동시 동일 spawn 의 check-then-act race 차단.
    async with _admission_lock(user_id, work_id, resolved):
        # 멱등성(I1) — 발급된 chain_id 가 이미 존재(any status)면 재-spawn 버림:
        # create_chain 덮어쓰기 + RT 재-enqueue 방지. dispatch_to 후속(새 uuid)은 해당 X.
        # admission 잠금 안이라 동시 동일 chain_id 도 직렬화 → race-safe.
        if chain_id is not None and await _chain_id_exists(cm, user_id, work_id, cid):
            await cm.append_trail(
                user_id,
                work_id,
                resolved,
                cid,
                {
                    "event": "spawn_duplicate_chain_id",
                    "dropped_chain_id": cid,
                    "pipeline_id": full_pid,
                },
            )
            log.info(
                "idempotent drop: chain_id %s 이미 존재 (persona %s, %s)", cid, resolved, full_pid
            )
            return cid
        dup = await _find_pending_duplicate(cm, user_id, work_id, resolved, full_pid)
        if dup is not None:
            # 버림 — create 안 함. 흡수된 대기 chain 의 trail 에 감사 1줄(비노출). 무신호(RAW 0).
            await cm.append_trail(
                user_id,
                work_id,
                resolved,
                dup,
                {"event": "spawn_coalesced", "dropped_chain_id": cid, "pipeline_id": full_pid},
            )
            log.info(
                "admission coalesced: dup spawn %s (persona %s, %s) → 대기건 %s 흡수",
                cid,
                resolved,
                full_pid,
                dup,
            )
            return cid  # echo (체인 안 띄움)
        await cm.create_chain(user_id, work_id, cid, full_pid, resolved, trigger)
        # producer pre-push — 모든 step 의 RT 를 persona 큐에 enqueue + rt_enqueued RAW.
        steps_list, context, _ = build_chain_context(user_id, work_id, cid, trigger, pipeline)
        await _enqueue_all_rts(user_id, work_id, cid, steps_list, context)
    # worker 보장 + 깨움 — enqueue 후 (RAW 순서 보존: rt_enqueued < rt_started).
    w = await ensure_worker(user_id, work_id, resolved)
    w.wake.set()
    return cid
