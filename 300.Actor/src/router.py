"""Actor REST endpoints — POST /dispatch (SSE) + POST /tool/{tool_name} (sync).

동시성: persona 별 dispatch 슬롯 + tool 풀 분리 (src/slots.py — cap = engine.config).
포화 시 즉시 503 + Retry-After (포화 ≠ 실패 — DRO 가 시간예산 backoff 로 재시도, B-1).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from venezia_contracts.models.dro_api.error import ErrorCode

from . import dispatcher, errors, slots, tools
from .cm_client import get_cm_client

log = logging.getLogger(__name__)
router = APIRouter()

_RETRY_AFTER = {"Retry-After": "1"}


@router.post("/dispatch")
async def dispatch_endpoint(body: dict[str, Any] = Body(...)):
    """body: {chain_id, rt_id, user_id, work_id, persona}"""
    chain_id = body.get("chain_id")
    rt_id = body.get("rt_id")
    user_id = body.get("user_id")
    work_id = body.get("work_id")
    persona = body.get("persona")
    if not (chain_id and rt_id and user_id and work_id) or persona is None:
        raise HTTPException(400, "chain_id, rt_id, user_id, work_id, persona required")

    pid = int(persona)
    try:
        acquired = await slots.try_acquire_persona(pid)
    except RuntimeError:
        # engine.config 미등재 persona — 슬롯 없이 진행, handle() 이 SSE error 로 거절
        # (기존 계약 보존: dispatch 는 200 SSE 를 열고 error 이벤트로 보고)
        acquired = None
    if acquired is False:
        return JSONResponse(
            errors.envelope(ErrorCode.rate_limited, "actor busy (persona slot saturated)"),
            status_code=503,
            headers=_RETRY_AFTER,
        )

    async def _stream():
        try:
            async for chunk in dispatcher.handle(user_id, work_id, chain_id, rt_id, pid):
                yield chunk
        finally:
            if acquired:
                slots.release_persona(pid)

    return StreamingResponse(_stream(), media_type="text/event-stream")


async def _record_tool_rt(body: dict[str, Any], result: Any) -> None:
    """tool RT 출력을 CM 레코드(rts/{rt_id}.json)에 기록 — tool=RT 통일(N-7), LLM /dispatch 대칭.
    식별자 미비(구 호출/단건 tool)면 no-op. CM 실패는 best-effort (DRO 가 이어서 finalize)."""
    rt_id = body.get("rt_id")
    chain_id = body.get("chain_id")
    persona = body.get("persona")
    user_id = body.get("user_id")
    work_id = body.get("work_id")
    if not (rt_id and chain_id and user_id and work_id) or persona is None:
        return
    output = result if isinstance(result, dict) else {"result": result}
    try:
        await get_cm_client().patch_rt(
            user_id,
            work_id,
            int(persona),
            chain_id,
            rt_id,
            {"output": output, "state": "done"},
        )
    except Exception:  # noqa: BLE001
        log.warning("tool RT record failed rt_id=%s", rt_id)


@router.post("/tool/{tool_name:path}")
async def tool_endpoint(tool_name: str, body: dict[str, Any] = Body(default={})):
    """DRO 가 직접 호출하는 tool dispatch endpoint.

    body: `{"params": {...}}`
    응답 (성공 외 = ErrorEnvelope {"error":{"code","message"}} — DRO·Nexus 동형):
      200 {"status": "success", "result": <tool 결과>}
      404 code=not_found        — 미등록 tool
      400 code=validation_failed — params non-dict / handler TypeError
      500 code=internal          — handler 내부 예외
      503 code=rate_limited + Retry-After — tool 풀 포화
          (dispatch 와 별도 풀, engine.config tools.max_concurrency)
    """
    handler = tools.get(tool_name)
    if handler is None:
        return JSONResponse(
            errors.envelope(ErrorCode.not_found, f"tool not registered: {tool_name}"),
            status_code=404,
        )

    if not await slots.try_acquire_tool():
        return JSONResponse(
            errors.envelope(ErrorCode.rate_limited, "tool pool saturated"),
            status_code=503,
            headers=_RETRY_AFTER,
        )

    try:
        params = (body or {}).get("params") or {}
        if not isinstance(params, dict):
            return JSONResponse(
                errors.envelope(ErrorCode.validation_failed, "params must be a dict"),
                status_code=400,
            )
        try:
            result = await handler(**params)
        except TypeError as e:
            return JSONResponse(
                errors.envelope(ErrorCode.validation_failed, str(e)),
                status_code=400,
            )
        # tool=RT 통일(N-7) — DRO 가 rt 식별자를 주면 tool 출력을 그 RT 레코드에 기록
        # (LLM /dispatch 의 patch_rt 대칭, 1차 writer). DRO 가 이어서 completed_at·bind 마무리.
        await _record_tool_rt(body, result)
        return {"status": "success", "result": result}
    except Exception as e:  # noqa: BLE001
        log.exception("tool call failed: %s", tool_name)
        return JSONResponse(
            errors.envelope(ErrorCode.internal, str(e)[:500]),
            status_code=500,
        )
    finally:
        slots.release_tool()
