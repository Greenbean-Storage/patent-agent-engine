"""DRO chain orchestration — P{NN} 전용. step/RT/tool 실행 헬퍼 (C1 — 이벤트 구동 worker).

chain 구동(producer/worker/facade)은 `worker.py` 소유 — 본 모듈은 그 구동이 호출하는
**step 실행 헬퍼**만 둔다 (`_run_steps`/`_run_one_step`/`_dispatch_llm_step`/`_dispatch_rt`/
`_exec_tool_call`/`_enqueue_all_rts`/`_create_and_push_rt`/`_build_rt_input` 등) + producer·worker
공용 `build_chain_context`.

흐름 (worker 모델):
  Nexus control / dispatch_to → `worker.run_chain` (producer): chain 생성 + step→RT resolve +
    persona 큐 순차 enqueue(`_enqueue_all_rts`, 모든 rt_enqueued RAW) + worker 깨움.
  (session,persona) 당 단일 `worker._drive_chain` 가 persona 큐를 순차 소비:
  → pipeline step 순회 (여기 `_run_steps`)
  → step.instructions = LLM step (큐 pop → Actor /dispatch SSE)
  → step.tool = DRO direct tool (Actor /tool/{name}, LLM 없음)
  → step list nesting (= 정적 병렬) = asyncio.gather (step-unit 안에서만 동시)
  → 마지막 step → dispatch_to.actions[dispatch_choice] 의 chain 들을 `run_chain` 으로 핸드오프
  → chain 종료 → chain_completed RAW.

같은 persona 의 chain 은 worker 가 한 번에 하나씩 직렬 구동 (구 "동시 실행" 폐기).
race 자료는 file-key asyncio.Lock 으로 처리 (CM).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import event_sse
from .branch_evaluator import substitute_placeholders
from .cm_client import get_cm_client
from .config import settings
from .dispatcher import dispatch_tool, dispatch_with_retry

log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# Chain context 합성 (C1 — producer 의 pre-push · worker 의 구동이 공용)
# ---------------------------------------------------------------------------


def build_chain_context(
    user_id: str,
    work_id: str,
    chain_id: str,
    trigger: dict[str, Any],
    pipeline: dict[str, Any],
) -> tuple[list[Any], dict[str, Any], str | None]:
    """(steps_list, context, last_step_id) 반환. trigger+pipeline 에서 **결정적**으로 만들어
    producer(`worker.run_chain` 의 `_enqueue_all_rts`)와 worker(`worker._drive_chain` 의
    `_run_steps`)가 동일 context 를 갖게 한다 — 둘이 다른 task frame 이고 재시작(C2) 시
    producer frame 이 사라져도 CM(chain.trigger)+pipeline 에서 재구성되므로 인메모리
    producer 상태 의존이 없다 (이벤트 구동 worker 모델의 핵심)."""
    parent_outputs = (trigger or {}).get("parent_outputs") or {}
    user_input = (trigger or {}).get("user_input") or {}
    steps_list = pipeline.get("steps") or []
    last_step_id: str | None = None
    if steps_list:
        last = steps_list[-1]
        if isinstance(last, list) and last:
            tail = last[-1]
            if isinstance(tail, dict):
                last_step_id = str(tail.get("id", ""))
        elif isinstance(last, dict):
            last_step_id = str(last.get("id", ""))
    context: dict[str, Any] = {
        "inputs": {
            "user_id": user_id,
            "work_id": work_id,
            "chain_id": chain_id,
        },
        "steps": {},
        "parent_outputs": parent_outputs,
        "user_input": user_input,
        "__pipeline_id__": pipeline.get("pipeline_id", ""),
        "__persona__": pipeline.get("persona"),
        "__pipeline_dispatch_to__": pipeline.get("dispatch_to"),
        "__last_step_id__": last_step_id,
    }
    return steps_list, context, last_step_id


# ---------------------------------------------------------------------------
# Step 진행
# ---------------------------------------------------------------------------


async def _run_steps(
    user_id: str,
    work_id: str,
    chain_id: str,
    steps: list[Any],
    context: dict[str, Any],
) -> None:
    cm = get_cm_client()
    persona = int(context.get("__persona__") or 0)
    # C1: RT 사전 push(_enqueue_all_rts)는 producer(worker.run_chain)가 이미 수행 — 여기선
    # step 순회하며 worker 가 그 RT 들을 pop·dispatch. (구 progress_chain 의 in-line pre-push 폐기)

    for step in steps:
        if isinstance(step, list):
            # 정적 병렬 group — list nesting
            await cm.append_trail(
                user_id,
                work_id,
                persona,
                chain_id,
                {
                    "event": "parallel_started",
                    "count": len(step),
                },
            )
            await asyncio.gather(
                *[_run_one_step(user_id, work_id, chain_id, sub, context) for sub in step]
            )
            await cm.append_trail(
                user_id,
                work_id,
                persona,
                chain_id,
                {
                    "event": "parallel_done",
                    "count": len(step),
                },
            )
        elif isinstance(step, dict):
            await _run_one_step(user_id, work_id, chain_id, step, context)
        else:
            raise RuntimeError(f"unexpected step shape: {type(step).__name__}")


async def _run_one_step(
    user_id: str,
    work_id: str,
    chain_id: str,
    step: dict[str, Any],
    context: dict[str, Any],
) -> None:
    get_cm_client()
    # 재시작 복구 (A-3) — 이미 완료된 step(rehydrate 로 output 보유)은 재실행 skip.
    # normal flow 에선 아직 안 채워졌으므로 미발동 — restart 시에만 done step 을 건너뛴다.
    sid = step.get("id")
    if sid is not None and sid in (context.get("steps") or {}):
        return
    has_instructions = bool(step.get("instructions"))
    has_tool = bool(step.get("tool"))
    if has_instructions and has_tool:
        raise RuntimeError(
            f"step '{step.get('id')}' has both 'instructions' and 'tool' — "
            "LLM step (instructions) 또는 tool step (tool) 중 하나만 허용"
        )
    if has_instructions:
        persona = _resolve_persona(step, context)
        output = await _dispatch_llm_step(user_id, work_id, chain_id, step, context, persona)
        context["steps"][step["id"]] = output
        return
    if has_tool:
        output = await _exec_tool_call(user_id, work_id, chain_id, step, context)
        context["steps"][step["id"]] = output
        return
    raise RuntimeError(
        f"step '{step.get('id')}' has neither 'instructions' nor 'tool' — "
        "P{NN} 포맷에선 LLM step 또는 tool step 만 허용 (구설계 step.type 폐기)"
    )


# ---------------------------------------------------------------------------
# RT 생성·dispatch
# ---------------------------------------------------------------------------


def _is_rt_step(step: dict[str, Any]) -> bool:
    """모든 step 이 RT — LLM step(instructions) 또는 tool step(tool). (tool=RT 통일, N-7)"""
    return bool(step.get("instructions") or step.get("tool"))


async def _enqueue_all_rts(
    user_id: str,
    work_id: str,
    chain_id: str,
    steps: list[Any],
    context: dict[str, Any],
) -> None:
    persona = int(context.get("__persona__") or 0)
    for step in steps:
        if isinstance(step, list):
            for sub in step:
                if isinstance(sub, dict) and _is_rt_step(sub):
                    rt_id = await _create_and_push_rt(user_id, work_id, chain_id, sub, context)
                    raw_payload = {"chain_id": chain_id, "rt_id": rt_id, "step_id": sub["id"]}
                    await event_sse.emit_raw(
                        user_id, work_id, "rt_enqueued", raw_payload, persona=persona, step=sub
                    )
        elif isinstance(step, dict) and _is_rt_step(step):
            rt_id = await _create_and_push_rt(user_id, work_id, chain_id, step, context)
            raw_payload = {"chain_id": chain_id, "rt_id": rt_id, "step_id": step["id"]}
            await event_sse.emit_raw(
                user_id, work_id, "rt_enqueued", raw_payload, persona=persona, step=step
            )


async def _create_and_push_rt(
    user_id: str,
    work_id: str,
    chain_id: str,
    step: dict[str, Any],
    context: dict[str, Any],
) -> str:
    cm = get_cm_client()
    rt_id = str(uuid.uuid4())
    persona = _resolve_persona(step, context)
    pipeline_id = step.get("pipeline_id") or context.get("__pipeline_id__") or ""
    is_tool = bool(step.get("tool"))
    rt = {
        "rt_id": rt_id,
        "chain_id": chain_id,
        "persona": persona,
        "step_id": step["id"],
        "step_type": "tool_task" if is_tool else "llm_task",
        "pipeline_id": pipeline_id,
        "input": (
            _build_tool_rt_input(step, context)
            if is_tool
            else _build_rt_input(step, _context_with_last_step_flag(step, context))
        ),
        "state": "pending",
        "retry_count": 0,
        "max_retries": 3,
        "created_at": _now(),
    }
    await _validate_rt_schema(cm, user_id, work_id, persona, chain_id, rt)
    await cm.create_rt(user_id, work_id, persona, chain_id, rt)
    await cm.persona_queue_push(user_id, work_id, persona, rt_id, chain_id)
    await cm.append_trail(
        user_id,
        work_id,
        persona,
        chain_id,
        {
            "event": "rt_enqueued",
            "rt_id": rt_id,
            "step_id": step["id"],
        },
    )
    return rt_id


async def _dispatch_llm_step(
    user_id: str,
    work_id: str,
    chain_id: str,
    step: dict[str, Any],
    context: dict[str, Any],
    persona: int,
) -> Any:
    """LLM step 1회 dispatch. Actor 의 with_backoff 가 vendor retry 처리."""
    cm = get_cm_client()
    # chain-scoped pop — persona 큐는 같은 persona 여러 chain 공유 → 이 chain 의 RT 만 pop
    # (타 chain RT 오소비 동시성 버그 방지). lease 만료는 CM lazy 제거.
    rt_id = await _pop_or_create_step_rt(user_id, work_id, chain_id, step, context, persona)

    rt = await cm.get_rt(user_id, work_id, persona, chain_id, rt_id)
    substituted = substitute_placeholders(rt.get("input", {}), context)
    if isinstance(substituted, dict):
        substituted["context"] = context
    await cm.patch_rt(
        user_id,
        work_id,
        persona,
        chain_id,
        rt_id,
        {"input": substituted, "state": "in_flight"},
    )

    result = await _dispatch_rt(user_id, work_id, chain_id, rt_id, persona, step)
    # structured 가 dict 또는 list (top-level array root, e.g., update_roadmap) 면 unwrap.
    if isinstance(result, dict) and isinstance(result.get("structured"), dict | list):
        return result["structured"]
    return result


def _resolve_persona(step: dict[str, Any], context: dict[str, Any]) -> int:
    p = context.get("__persona__")
    if p is None:
        raise RuntimeError(
            f"persona not defined for step '{step.get('id')}' — "
            "pipeline top-level persona 필드 누락 (P{NN} 포맷의 cascading 결과에 persona 있어야 함)"
        )
    return int(p)


_CONTRACT_LOADER = None  # type: ignore[assignment]


def _contract_loader():
    global _CONTRACT_LOADER
    if _CONTRACT_LOADER is False:
        return None
    if _CONTRACT_LOADER is None:
        try:
            from venezia_contracts import ContractLoader

            _CONTRACT_LOADER = ContractLoader()
        except Exception as e:  # noqa: BLE001
            log.warning("ContractLoader unavailable, RT schema validation skipped: %s", e)
            _CONTRACT_LOADER = False
            return None
    return _CONTRACT_LOADER


async def _validate_rt_schema(
    cm, user_id: str, work_id: str, persona: int, chain_id: str, rt: dict
) -> None:
    loader = _contract_loader()
    if loader is None:
        return
    result = loader.validate("reasoning_task", rt)
    if result:
        return
    log.warning("RT schema invalid rt_id=%s errors=%s", rt.get("rt_id"), result.errors[:3])
    try:
        await cm.append_trail(
            user_id,
            work_id,
            persona,
            chain_id,
            {
                "event": "schema_violation",
                "contract": "reasoning_task",
                "rt_id": rt.get("rt_id"),
                "errors": result.errors[:5],
            },
        )
    except Exception:  # noqa: BLE001
        log.warning("trail append failed for schema_violation")


def _context_with_last_step_flag(step: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    is_last = str(step.get("id", "")) == str(context.get("__last_step_id__") or "")
    return {**context, "__is_last_step__": is_last}


def _load_output_contract(contract_id: str, persona: int | None) -> dict[str, Any] | None:
    if not contract_id or persona is None:
        return None
    import json as _json

    prefix = f"{persona:02d}."
    contracts_root = Path("/contracts")
    if not contracts_root.exists():
        contracts_root = Path(settings.PIPELINES_DIR).parent / "@contracts"
    if not contracts_root.exists():
        contracts_root = Path("/app/@contracts")
    if not contracts_root.exists():
        return None
    for child in contracts_root.iterdir():
        if child.is_dir() and child.name.startswith(prefix):
            schema_file = child / "stages" / f"{contract_id}.schema.json"
            if schema_file.exists():
                try:
                    return _json.loads(schema_file.read_text(encoding="utf-8"))
                except Exception:
                    return None
    return None


def _build_rt_input(step: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """RT.input 합성 (P{NN} 전용). Actor 의 composer 가 prompt 합성."""
    persona = context.get("__persona__")
    output_contract_id = step.get("output_contract")
    response_schema = (
        _load_output_contract(output_contract_id, persona) if output_contract_id else None
    )

    dispatch_to_meta = context.get("__pipeline_dispatch_to__")
    dispatch_choice_guide: dict[int, str] | None = None
    if dispatch_to_meta and context.get("__is_last_step__"):
        actions = dispatch_to_meta.get("actions") or []
        if len(actions) > 1:
            dispatch_choice_guide = {}
            for idx, action_list in enumerate(actions):
                if not isinstance(action_list, list):
                    continue
                if len(action_list) == 0:
                    dispatch_choice_guide[idx] = "(exit — chain 종료)"
                else:
                    dispatch_choice_guide[idx] = "다음 파이프라인: " + ", ".join(action_list)

    return {
        "prompt": "",
        "system_prompt": "",
        "persona_prompt": step.get("system_prompt") or "",
        "inject_context_spec": step.get("effective_inject_context") or {},
        "recommended_context_spec": step.get("effective_recommended_context") or {},
        "fragments": step.get("effective_fragments") or {},
        "instructions": step.get("instructions") or None,
        "dispatch_choice_guide": dispatch_choice_guide,
        "context": {
            "inputs": context.get("inputs", {}),
            "parent_outputs": context.get("parent_outputs", {}),
        },
        "available_tools": step.get("effective_llm_tools") or [],
        "media_refs": step.get("media_refs", []),
        "response_schema": response_schema,
        "step_definition": {
            "id": str(step.get("id", "")),
            "output_contract": output_contract_id,
        },
    }


def _build_tool_rt_input(step: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """tool RT.input 합성 (tool=RT 통일, N-7). composer 미경유 — prompt 는 vestigial 빈 문자열.
    params_spec 은 미치환 보존(재시작 시 재구성한 context 로 재substitute)."""
    return {
        "prompt": "",
        "tool": step["tool"],
        "params_spec": step.get("params") or step.get("params_map") or {},
        "inject_context_spec": step.get("effective_inject_context") or {},
        "bind": step.get("bind"),
        "step_definition": {
            "id": str(step.get("id", "")),
            "tool": step["tool"],
        },
    }


async def _pop_or_create_step_rt(
    user_id: str,
    work_id: str,
    chain_id: str,
    step: dict[str, Any],
    context: dict[str, Any],
    persona: int,
) -> str:
    """이 step 의 RT 를 persona 큐에서 chain-scoped pop — 비었거나 mismatch/이미 done 이면
    새로 만들어 push 후 pop (LLM·tool 공용). lease ttl = RT 시간예산.
    """
    cm = get_cm_client()
    lease_ttl = settings.DISPATCH_RETRY_BUDGET_S + settings.DISPATCH_TIMEOUT_S
    popped = await cm.persona_queue_pop(
        user_id, work_id, persona, chain_id=chain_id, lease_ttl_s=lease_ttl
    )
    if popped.get("empty"):
        rt_id = await _create_and_push_rt(user_id, work_id, chain_id, step, context)
        await cm.persona_queue_pop(
            user_id, work_id, persona, chain_id=chain_id, lease_ttl_s=lease_ttl
        )
        return rt_id
    rt_id = popped["rt_id"]
    popped_rt = await cm.get_rt(user_id, work_id, persona, chain_id, rt_id)
    if (popped_rt.get("step_id") != step["id"]) or (popped_rt.get("state") == "done"):
        rt_id = await _create_and_push_rt(user_id, work_id, chain_id, step, context)
        await cm.persona_queue_pop(
            user_id, work_id, persona, chain_id=chain_id, lease_ttl_s=lease_ttl
        )
    return rt_id


async def _dispatch_rt(
    user_id: str, work_id: str, chain_id: str, rt_id: str, persona: int, step: dict[str, Any]
) -> dict[str, Any]:
    cm = get_cm_client()
    sse_events: list[dict[str, Any]] = []

    async def _on_event(evt: dict[str, Any]) -> None:
        sse_events.append({"ts": _now(), "type": evt["type"], "data": evt.get("data", {})})
        internal_type = f"rt_{evt['type']}"
        # Nexus 로 raw push — Actor SSE inner data 를 payload 로 (Nexus 가 structured/text 추출).
        # rt_started 에 step 의 사용자 문구(display_status) 동봉 → progress 원천(#6).
        evt_data = evt.get("data", {}) if isinstance(evt.get("data"), dict) else {}
        await event_sse.emit_raw(
            user_id,
            work_id,
            internal_type,
            evt_data,
            persona=persona,
            step=step if internal_type == "rt_started" else None,
        )

    await cm.append_trail(
        user_id,
        work_id,
        persona,
        chain_id,
        {
            "event": "rt_started",
            "rt_id": rt_id,
            "persona": persona,
        },
    )
    try:
        result = await dispatch_with_retry(
            persona, chain_id, rt_id, user_id, work_id, on_event=_on_event
        )
        await cm.patch_rt(
            user_id,
            work_id,
            persona,
            chain_id,
            rt_id,
            {
                "output": result,
                "state": "done",
                "completed_at": _now(),
                "sse_events_append": sse_events,
            },
        )
        await cm.append_trail(
            user_id, work_id, persona, chain_id, {"event": "rt_completed", "rt_id": rt_id}
        )
        return result
    except Exception as e:  # noqa: BLE001
        await cm.patch_rt(
            user_id,
            work_id,
            persona,
            chain_id,
            rt_id,
            {"state": "failed", "error": {"message": str(e)}, "sse_events_append": sse_events},
        )
        await cm.append_trail(
            user_id,
            work_id,
            persona,
            chain_id,
            {"event": "rt_failed", "rt_id": rt_id, "error": str(e)},
        )
        raise
    finally:
        try:
            # 본인 rt_id 의 lease 만 해제 — 동시 다건 lease 의 타 기록 보존 (D-1)
            await cm.persona_queue_release(user_id, work_id, persona, rt_id)
        except Exception:  # noqa: BLE001
            log.warning("queue lease release failed for rt %s (persona %s)", rt_id, persona)


# ---------------------------------------------------------------------------
# Tool step (DRO direct, LLM 없는 경로)
# ---------------------------------------------------------------------------


def _summarize_params(params: dict[str, Any]) -> dict[str, Any]:
    """tool 호출 params 의 trail-friendly 요약. queries / 검색어 list 같은 핵심은
    `_full` 키로 전수 보존해 simulator 가 박스로 출력할 수 있게 한다.
    """
    out: dict[str, Any] = {}
    for k, v in (params or {}).items():
        if v is None or isinstance(v, bool | int | float):
            out[k] = v
        elif isinstance(v, str):
            out[k] = v if len(v) <= 80 else v[:80] + "…"
        elif isinstance(v, list):
            # 검색어/특허 list 같은 핵심 도메인 key 는 전수 보존
            full_items: list[Any] = []
            for x in v:
                if isinstance(x, dict):
                    full_items.append(
                        {ik: iv for ik, iv in x.items() if not isinstance(iv, dict | list)}
                    )
                elif isinstance(x, str):
                    full_items.append(x[:200] + "…" if len(x) > 200 else x)
                else:
                    full_items.append(x)
            out[k] = {"_len": len(v), "_full": full_items}
        elif isinstance(v, dict):
            out[k] = {"_keys": list(v.keys())[:10]}
        else:
            out[k] = {"_type": type(v).__name__}
    return out


_CM_RESOURCE_FETCHERS = {
    "invention_object_model": "get_iom",
    "concept_discovery_stack": "get_concept_discovery_stack",
    "concept_maturity_model": "get_concept_maturity_model",
    "conversation": "get_conversation",
    "user_roadmap": "get_user_roadmap",
}


def _split_cm_path(path: str) -> tuple[str, str]:
    """cm:// path 를 (resource, RFC 6901 pointer) 로 split.

    - `cm://invention_object_model`               → ("invention_object_model", "")
    - `cm://concept_discovery_stack/purpose`      → ("concept_discovery_stack", "/purpose")
    - `cm://concept_discovery_stack/sub/field`    → ("concept_discovery_stack", "/sub/field")

    dot-path (`X.field`) 표기는 폐기 — RFC 6901 통일 이후 발견 시 fail-loud.
    """
    if "." in path and not path.startswith("dialogs/"):
        raise RuntimeError(
            f"cm:// path 의 dot-path 표기는 폐기 — RFC 6901 slash 표기 사용: {path!r}"
        )
    head, sep, rest = path.partition("/")
    pointer = f"/{rest}" if sep and rest else ""
    return head, pointer


async def _resolve_inject_context(
    user_id: str,
    work_id: str,
    chain_id: str,
    inject_spec: dict[str, Any],
) -> dict[str, Any]:
    """tool step 의 inject_context 사전 fetch — cm:// 를 server-side pointer fetch 로 변환.

    LLM step 은 Actor 의 composer 가 처리하지만 tool step 은 그런 경로가 없어
    orchestrator 가 placeholder 치환 전에 같은 역할을 한다. P-E 정합: client-side walk
    함수 (`_walk`) 폐기, 모든 부분 read 는 CM `?pointer=/path` 로만.
    """
    cm = get_cm_client()
    out: dict[str, Any] = {}
    for name, spec in (inject_spec or {}).items():
        if not isinstance(spec, str) or not spec.startswith("cm://"):
            out[name] = spec
            continue
        path = spec.removeprefix("cm://")
        # P-A v3: 페르소나 누적 dialog — `dialogs/{persona}.{name}` 그대로 (resource 단일 fetch)
        if path.startswith("dialogs/"):
            rest = path.removeprefix("dialogs/").removesuffix(".json")
            parts = rest.split(".", 1)
            if len(parts) == 2 and parts[0].isdigit():
                out[name] = await cm.get_persona_dialog(user_id, work_id, int(parts[0]), parts[1])
            else:
                out[name] = None
            continue
        resource, pointer = _split_cm_path(path)
        fetcher_name = _CM_RESOURCE_FETCHERS.get(resource)
        if fetcher_name is None:
            raise RuntimeError(f"cm:// 미지원 resource: {resource!r} (spec={spec!r})")
        fetcher = getattr(cm, fetcher_name)
        out[name] = await fetcher(user_id, work_id, pointer=pointer)
    return out


async def _exec_tool_call(
    user_id: str,
    work_id: str,
    chain_id: str,
    step: dict[str, Any],
    context: dict[str, Any],
) -> Any:
    """step.tool → Actor POST /tool/{name} (LLM 없는 빠른 경로).

    `cm.*` 카테고리 도구는 CM 자원 쓰기/읽기를 위해 user_id/work_id 가 필요.
    파이프라인 params 에는 비즈니스 payload 만 명시되어 있고 user/invention 식별자는
    DRO 가 자동 주입.
    """
    cm = get_cm_client()
    persona = int(context.get("__persona__") or 0)
    tool_name = step["tool"]
    step_id = step["id"]  # tool=RT 통일(N-7) — 모든 step 은 RT 라 id 필수 (loader 가 부여)
    # tool=RT 통일(N-7) — tool step 도 RT 로 pop/기록·rt_* 이벤트 발사 (LLM 진행 관측 대칭)
    rt_id = await _pop_or_create_step_rt(user_id, work_id, chain_id, step, context, persona)
    inject_spec = step.get("effective_inject_context") or {}
    injected = await _resolve_inject_context(user_id, work_id, chain_id, inject_spec)
    ctx_for_subst: dict[str, Any] = {**context, **injected}
    params_spec = step.get("params") or step.get("params_map") or {}
    params = substitute_placeholders(params_spec, ctx_for_subst)
    if not isinstance(params, dict):
        params = {}
    if tool_name.startswith(("cm.", "staging.", "maturity.", "roadmap.")):
        params = {**params, "user_id": user_id, "work_id": work_id}

    # RT in_flight + rt_started (LLM 대칭 — 진행 관측 균일, N-7)
    await cm.patch_rt(
        user_id,
        work_id,
        persona,
        chain_id,
        rt_id,
        {"input": {"tool": tool_name, "params": params}, "state": "in_flight"},
    )
    await cm.append_trail(
        user_id,
        work_id,
        persona,
        chain_id,
        {"event": "rt_started", "rt_id": rt_id, "persona": persona},
    )
    await event_sse.emit_raw(user_id, work_id, "rt_started", {}, persona=persona, step=step)

    await cm.append_trail(
        user_id,
        work_id,
        persona,
        chain_id,
        {
            "event": "tool_call_started",
            "step_id": step_id,
            "tool": tool_name,
            "params_keys": list(params.keys()),
            "params_summary": _summarize_params(params),
            "_debug": {
                "params_spec": params_spec,
                "ctx_steps_keys": list((context.get("steps") or {}).keys()),
            },
        },
    )

    try:
        resp = await dispatch_tool(
            tool_name,
            params,
            user_id=user_id,
            work_id=work_id,
            chain_id=chain_id,
            persona=persona,
            step_id=step_id,
            rt_id=rt_id,
        )
    except Exception as e:
        await cm.patch_rt(
            user_id,
            work_id,
            persona,
            chain_id,
            rt_id,
            {"state": "failed", "error": {"message": str(e)[:300]}},
        )
        await cm.append_trail(
            user_id,
            work_id,
            persona,
            chain_id,
            {
                "event": "tool_call_failed",
                "step_id": step_id,
                "tool": tool_name,
                "error": str(e)[:200],
            },
        )
        await cm.append_trail(
            user_id,
            work_id,
            persona,
            chain_id,
            {"event": "rt_failed", "rt_id": rt_id, "error": str(e)[:200]},
        )
        await event_sse.emit_raw(
            user_id, work_id, "rt_error", {"message": str(e)[:200]}, persona=persona
        )
        try:
            await cm.persona_queue_release(user_id, work_id, persona, rt_id)
        except Exception:  # noqa: BLE001
            log.warning("queue lease release failed for tool rt %s", rt_id)
        raise

    status = (resp or {}).get("status") if isinstance(resp, dict) else None
    payload = (resp or {}).get("result") if isinstance(resp, dict) and "result" in resp else resp

    summary: dict[str, Any] = {}
    if isinstance(payload, dict):
        if isinstance(payload.get("patents"), list):
            patents = payload["patents"]
            summary["patents_count"] = len(patents)
            summary["patents_preview"] = [
                {
                    "application_number": p.get("application_number"),
                    "title": (p.get("title") or "")[:80],
                }
                for p in patents[:5]
                if isinstance(p, dict)
            ]
        if isinstance(payload.get("query"), str):
            summary["query"] = payload["query"][:100]
        if isinstance(payload.get("figure_bytes_b64"), str):
            summary["figure_bytes"] = len(payload["figure_bytes_b64"]) * 3 // 4
            summary["chosen_tool"] = payload.get("chosen_tool")
        if isinstance(payload.get("review"), dict):
            summary["overall_pass"] = payload["review"].get("overall_pass")

    await cm.append_trail(
        user_id,
        work_id,
        persona,
        chain_id,
        {
            "event": "tool_call_done",
            "step_id": step_id,
            "tool": tool_name,
            "status": status,
            "summary": summary,
        },
    )

    # #12: maturity/roadmap 신호는 DRO 미발사 — Nexus 가 chain 완료(persona 2) 시
    # CM 에서 CMM/UR fetch → model.* WS push. tool 의 CM PUT 부수효과는 유지(진실 원천).
    bind = step.get("bind")
    output = {bind: payload} if bind else payload

    # rt_result RAW + RT done + rt_completed (LLM 대칭, N-7). Actor /tool 이 output 을 이미
    # 기록(B안)했으나 DRO 가 completed_at·trail 로 마무리 (LLM 의 _dispatch_rt 와 동형 이중기록).
    await event_sse.emit_raw(
        user_id,
        work_id,
        "rt_result",
        payload if isinstance(payload, dict) else {"result": payload},
        persona=persona,
    )
    await cm.patch_rt(
        user_id,
        work_id,
        persona,
        chain_id,
        rt_id,
        {
            "output": output if isinstance(output, dict) else {"result": output},
            "state": "done",
            "completed_at": _now(),
        },
    )
    await cm.append_trail(
        user_id, work_id, persona, chain_id, {"event": "rt_completed", "rt_id": rt_id}
    )
    try:
        await cm.persona_queue_release(user_id, work_id, persona, rt_id)
    except Exception:  # noqa: BLE001
        log.warning("queue lease release failed for tool rt %s", rt_id)
    return output
