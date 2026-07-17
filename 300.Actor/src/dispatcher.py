"""Actor dispatch handler — POST /dispatch SSE 응답.

P{NN} 전용 흐름 (동시성: persona 별 슬롯 — router 가 src/slots.py 로 집행):
  1. (router) persona 슬롯 try-acquire — 포화 즉시 503+Retry-After
  2. CM RT GET
  3. agent_state 로드
  4. persona → LLM SDK 인스턴스
  5. RT.input.effective_llm_tools → tool registry lookup (자기 chain fetch_* 만 허용)
  6. composer 로 single-text prompt 합성
     (persona_prompt + fragments + inject_context + recommended + instructions)
  7. SDK 호출
  8. agent_state PUT, RT output PATCH
  9. SSE result
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from venezia_contracts.models.dro_api.error import ErrorCode

from . import errors, sse, tools
from .cm_client import get_cm_client
from .composer import compose_prompt
from .config import settings
from .llm import create_session as create_llm_session
from .tools.fetch import make_fetch_tools

log = logging.getLogger(__name__)


def _accepts_persona(persona: int) -> bool:
    """수락 집합 = engine.config personas (구 ACTOR_PERSONAS env 폐기 — unified)."""
    from . import engine_config

    return persona in engine_config.persona_ids()


async def handle(
    user_id: str, work_id: str, chain_id: str, rt_id: str, persona: int
) -> AsyncIterator[str]:
    """SSE 스트림 generator. P{NN} 전용 — composer 필수.

    persona 는 DRO dispatch body 가 전달(3a) — Actor 가 brute-force 순회 없이 직접 RT read.
    """
    cm = get_cm_client()
    try:
        yield sse.event("started", {"rt_id": rt_id, "actor_id": settings.ACTOR_ID})

        # P-A v3: chain 자료는 persona sub-folder 안. DRO 가 dispatch body 로 persona 를 전달하므로
        # 해당 persona dir 에서 직접 RT read (구 1~6 brute-force 순회 폐기, 3a).
        if not _accepts_persona(persona):
            yield sse.event(
                "error",
                errors.envelope(
                    ErrorCode.not_found, f"persona {persona} not handled by this actor"
                ),
            )
            return
        rt: dict[str, Any] | None = await cm.get_rt(user_id, work_id, persona, chain_id, rt_id)
        if rt is None:
            yield sse.event(
                "error",
                errors.envelope(ErrorCode.not_found, f"RT {rt_id} not found for persona {persona}"),
            )
            return

        # 컨텍스트 ② — agent_state = vendor 원형 envelope (legacy 평문 = fail-loud)
        from .llm.state import parse_agent_state

        agent_state = await cm.get_agent_state(user_id, work_id, persona, chain_id)
        prior_state = parse_agent_state(agent_state)
        rt_input = rt.get("input") or {}

        # P{NN} 필수 키 검증 — composer 가 필요한 키.
        if "inject_context_spec" not in rt_input and "persona_prompt" not in rt_input:
            raise RuntimeError(
                f"RT input lacks P{{NN}} composer keys (inject_context_spec / persona_prompt) — "
                f"rt_id={rt_id}. 구설계 RT.input 폐기됨."
            )

        # Tool 등록 — LLM 의 llm_tools 에 자기 chain fetch_* 만 허용
        # (pipeline_walker 가 cascading 단계에서 막음).
        tool_names = rt_input.get("available_tools") or []
        loaded_tools: list[dict[str, Any]] = []
        for name in tool_names:
            handler = tools.get(name)
            if handler is None:
                log.warning("tool not registered: %s", name)
                continue
            loaded_tools.append({"name": name, "handler": handler})

        # D-3: step 이 선언한 llm_tools(available_tools)만 LLM 에 노출 — 선언이 실제 제어.
        # 선언 안 하면 fetch_* 미노출(현 전 pipeline 이 빈 선언 → fetch 도구 0개, future opt-in).
        fetch_tools = make_fetch_tools(
            cm, user_id, work_id, persona, chain_id, allowed_names=tool_names
        )

        yield sse.event(
            "progress",
            {
                "phase": "llm_call_started",
                "tools_loaded": [t["name"] for t in loaded_tools],
                "fetch_tools": [f.__name__ for f in fetch_tools],
            },
        )

        sess = create_llm_session(
            persona,
            prior_state=prior_state,
            step_id=rt.get("step_id"),
            pipeline_id=rt.get("pipeline_id"),
        )

        async def _cm_fetch(path: str):
            """cm://<resource>[/RFC6901_pointer] resolve — server-side pointer fetch 단일 경로.

            P-E 정합: client-side `_walk` 폐기, dot-path 표기 fail-loud.

            지원 path:
              - invention_object_model[/sub/path]
              - concept_discovery_stack[/sub/path]   (P-C)
              - concept_maturity_model[/sub/path]    (P-C)
              - conversation[/sub/path]              (DRO writer, 사용자 누적)
              - user_roadmap[/sub/path]              (top-level array — pointer="" 면 array 전체)
              - dialogs/<persona_int>.<name>.json    (페르소나 누적 dialog, 단일 resource)
            """
            if path.startswith("dialogs/"):
                rest = path.removeprefix("dialogs/").removesuffix(".json")
                parts = rest.split(".", 1)
                if parts[0].isdigit() and len(parts) == 2:
                    return await cm.get_persona_dialog(user_id, work_id, int(parts[0]), parts[1])
                if persona:
                    try:
                        return await cm.get_persona_dialog(
                            user_id, work_id, persona, parts[0] if parts else rest
                        )
                    except Exception:  # noqa: BLE001
                        return None
                return None

            if "." in path:
                raise RuntimeError(
                    f"cm:// path 의 dot-path 표기는 폐기 — RFC 6901 slash 표기 사용: {path!r}"
                )
            head, sep, rest = path.partition("/")
            pointer = f"/{rest}" if sep and rest else ""
            fetcher_map = {
                "invention_object_model": cm.get_invention_object_model,
                "concept_discovery_stack": cm.get_concept_discovery_stack,
                "concept_maturity_model": cm.get_concept_maturity_model,
                "conversation": cm.get_conversation,
                "user_roadmap": cm.get_user_roadmap,
            }
            fetcher = fetcher_map.get(head)
            if fetcher is None:
                raise RuntimeError(f"cm:// 미지원 resource: {head!r} (path={path!r})")
            return await fetcher(user_id, work_id, pointer=pointer)

        prompt_text = await compose_prompt(
            persona_prompt=rt_input.get("persona_prompt", ""),
            inject_context=rt_input.get("inject_context_spec") or {},
            recommended_context=rt_input.get("recommended_context_spec") or {},
            fragments=rt_input.get("fragments") or {},
            instructions=rt_input.get("instructions"),
            dispatch_choice_guide=rt_input.get("dispatch_choice_guide"),
            knowledge_root=Path("/app/@knowledge"),
            pipelines_root=Path("/pipelines"),
            cm_fetch=_cm_fetch,
        )
        system_prompt_text = ""

        resp_schema = rt_input.get("response_schema")
        ctx = rt_input.get("context") or {}
        await cm.append_trail(
            user_id,
            work_id,
            persona,
            chain_id,
            {
                "event": "llm_input_prepared",
                "rt_id": rt_id,
                "step_id": rt.get("step_id"),
                "persona": persona,
                "sdk": getattr(sess, "sdk", None),
                "model": getattr(sess, "model", None),
                "prompt_chars": len(prompt_text),
                "context_steps_keys": sorted(list((ctx.get("steps") or {}).keys())),
                "available_tools": [t["name"] for t in loaded_tools],
                "has_response_schema": bool(resp_schema),
                "response_schema_required": (
                    list(resp_schema.get("required", [])) if isinstance(resp_schema, dict) else []
                ),
                "media_refs_count": len(rt_input.get("media_refs") or []),
                "function_tools": [f.__name__ for f in fetch_tools],
            },
        )

        result = await sess.run(
            prompt=prompt_text,
            system_prompt=system_prompt_text,
            tools=loaded_tools,
            media_refs=rt_input.get("media_refs") or [],
            response_schema=resp_schema,
            context=ctx,
            function_tools=fetch_tools,
        )

        await cm.put_agent_state(user_id, work_id, persona, chain_id, sess.export_state())
        await cm.patch_rt(
            user_id,
            work_id,
            persona,
            chain_id,
            rt_id,
            {"output": result, "state": "done"},
        )

        yield sse.event("result", result)
    except Exception as e:  # noqa: BLE001
        log.exception("dispatch failed")
        yield sse.event("error", errors.envelope(ErrorCode.internal, str(e)))
