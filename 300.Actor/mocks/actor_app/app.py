"""actor:fake mock — 실 Actor 외부 표면의 mock 구현 (CHUNK 3-B).

- `GET /health` — 실 /health 동형 + `mock:true` 식별
- `POST /dispatch` — SSE fixture replay: started → progress → result | error.
  busy-marker → HTTP 503 "busy" + Retry-After (DRO 후보 fallback/backoff 트리거)
- `POST /tool/{name}` — canned 출력 (실 envelope 동형). 미등록 tool = 404

동시성: 실 Actor 는 persona 별 cap 세마포어(src/slots.py)지만 mock 은 즉답 replay 라
포화가 관측되지 않음 — cap 은 시뮬레이트하지 않고(divergence), 의도적 503 은
busy-marker 가 전담. 503 응답 형식(+Retry-After)은 실 router 와 동형.

fixture 키 해소 = 실 CM read (chain-only route) → RT 의 (pipeline_id, step_id).
mock 의 CM-write 0 — RT.output 은 DRO orchestrator 가 dispatch SSE result 로 PATCH (3c-2).
fixture miss = strict fail-loud (3g — SSE error → DRO ActorError).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from . import busy, canned, config, fixtures, rt_lookup, sse

log = logging.getLogger(__name__)

app = FastAPI(title="actor-mock")

_RETRY_AFTER = {"Retry-After": "1"}


def _err(code: str, message: str) -> dict:
    """ErrorEnvelope 동형 — 실 Actor errors.envelope() 과 같은 {"error":{"code","message"}}."""
    return {"error": {"code": code, "message": message}}


@app.get("/health")
def health() -> dict[str, object]:
    """compose healthcheck + 식별. 실 Actor /health 와 동형 + mock 플래그."""
    return {
        "status": "ok",
        "actor_id": config.ACTOR_ID,
        "personas": config.personas(),
        "tools": sorted(canned.CANNED),
        "llm_mode": "FIXTURE",
        "slots": None,  # mock 은 동시성 cap 비시뮬레이트 (즉답 replay — divergence 명기)
        "mock": True,
    }


@app.post("/dispatch")
async def dispatch_endpoint(body: dict[str, Any] = Body(...)):  # noqa: B008
    """body: {chain_id, rt_id, user_id, work_id, persona} — 실 router 와 동일 계약."""
    chain_id = body.get("chain_id")
    rt_id = body.get("rt_id")
    user_id = body.get("user_id")
    work_id = body.get("work_id")
    persona = body.get("persona")
    if not (chain_id and rt_id and user_id and work_id) or persona is None:
        raise HTTPException(400, "chain_id, rt_id, user_id, work_id, persona required")
    try:
        persona_int = int(persona)
    except (TypeError, ValueError) as e:
        raise HTTPException(400, f"persona must be an int, got {persona!r}") from e

    # marker 판정에 (pipeline_id, step_id) 가 필요해 stream 전에 RT read
    # (실 actor 는 started 후 read — 순서 차이는 DRO 소비 계약상 비관측).
    rt: dict[str, Any] | None = None
    rt_error: str | None = None
    try:
        rt = await rt_lookup.get_rt(user_id, work_id, chain_id, rt_id)
    except Exception as e:  # noqa: BLE001 — stream 안에서 error event 로 fail-loud
        rt_error = f"mock-actor CM RT read failed: {e}"
    if rt is not None and busy.marker_503(str(rt.get("pipeline_id")), str(rt.get("step_id"))):
        return JSONResponse(
            _err("rate_limited", "actor busy (persona slot saturated)"),
            status_code=503,
            headers=_RETRY_AFTER,
        )

    async def _stream() -> AsyncIterator[str]:
        yield sse.event("started", {"rt_id": rt_id, "actor_id": config.ACTOR_ID})
        if rt_error is not None:
            yield sse.event("error", _err("internal", rt_error))
            return
        if persona_int not in config.personas():
            yield sse.event(
                "error", _err("not_found", f"persona {persona_int} not handled by this actor")
            )
            return
        if rt is None:
            yield sse.event(
                "error", _err("not_found", f"RT {rt_id} not found for chain {chain_id}")
            )
            return
        yield sse.event(
            "progress",
            {
                "phase": "llm_call_started",
                "tools_loaded": [],
                "fetch_tools": [],
            },
        )
        pipeline_id = str(rt.get("pipeline_id"))
        step_id = str(rt.get("step_id"))
        try:
            structured = fixtures.load(pipeline_id, step_id)
        except fixtures.FixtureMiss as e:
            yield sse.event("error", _err("internal", str(e)))
            return
        yield sse.event(
            "result",
            {"text": f"(fixture {pipeline_id}/{step_id})", "structured": structured},
        )

    return StreamingResponse(_stream(), media_type="text/event-stream")


@app.post("/tool/{tool_name:path}")
async def tool_endpoint(tool_name: str, body: dict[str, Any] = Body(default={})):  # noqa: B008
    """canned tool dispatch — 실 router 의 응답 envelope 동형 (tool 풀 cap 은 비시뮬레이트)."""
    handler = canned.CANNED.get(tool_name)
    if handler is None:
        return JSONResponse(
            _err("not_found", f"tool not registered: {tool_name}"),
            status_code=404,
        )

    params = (body or {}).get("params") or {}
    if not isinstance(params, dict):
        return JSONResponse(
            _err("validation_failed", "params must be a dict"),
            status_code=400,
        )
    try:
        try:
            result = await handler(**params)
        except (TypeError, ValueError) as e:
            return JSONResponse(
                _err("validation_failed", str(e)),
                status_code=400,
            )
        return {"status": "success", "result": result}
    except Exception as e:  # noqa: BLE001
        log.exception("mock tool call failed: %s", tool_name)
        return JSONResponse(
            _err("internal", str(e)[:500]),
            status_code=500,
        )
