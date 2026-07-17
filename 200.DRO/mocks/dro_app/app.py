"""dro:fake mock — 실 DRO internal 표면의 mock 구현 (CHUNK 4).

- `GET /health` — 실 /health 동형 + `mock:true` 식별
- `POST /control/spawn` — 실 router 동일 타입검증(400 envelope 동형) ·
  pipeline_id 의 playlist 부재 = 404 pipeline_unknown (tape 존재 = 유효, fail-loud) ·
  202 {chain_id} + tape 재생 background task
- `POST /control/output` — 실 router 동형(C6 docx 빌드). mock 은 stateless 라 canned 응답 +
  RAW output_ready emit 만 (Nexus event_mapper → WS output.ready 통합 검증). 실 docx·CM 미영속.
- `GET /events/{u}/{w}` — SSE (실 헤더 동형). 무한 유지, 다중 구독 broadcast

mock 의 CM read/write 0 (stateless) — Nexus event_mapper 가 tape payload 만 forward.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import Body, FastAPI
from fastapi.responses import JSONResponse, StreamingResponse

from . import hub, tape_player

log = logging.getLogger(__name__)

app = FastAPI(title="dro-mock")


def _error(code: str, status: int, message: str) -> JSONResponse:
    """실 DRO errors.py 의 envelope 동형 — {"error": {code, message}}."""
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


@app.get("/health")
def health() -> dict[str, object]:
    """compose healthcheck + 식별. 실 DRO /health 동형 + mock 플래그."""
    return {
        "status": "ok",
        "service": "dro",
        "llm_mode": "FIXTURE",
        "mock": True,
        "pipelines": sorted(tape_player.PLAYLISTS),
    }


@app.post("/control/spawn", status_code=202)
async def control_spawn(body: dict[str, Any] = Body(...)):  # noqa: B008
    """실 router 와 동일 계약 — 202 후 tape 재생 (비동기, 실 spawn_chain 동형)."""
    user_id = body.get("user_id")
    work_id = body.get("work_id")
    pipeline_id = body.get("pipeline_id")
    chain_id = body.get("chain_id")
    persona = body.get("persona")
    if not (
        isinstance(user_id, str)
        and isinstance(work_id, str)
        and isinstance(pipeline_id, str)
        and isinstance(chain_id, str)
        and isinstance(persona, int)
    ):
        return _error(
            "validation_failed",
            400,
            "control/spawn: user_id/work_id/pipeline_id/chain_id(str) + persona(int) 필수",
        )
    if pipeline_id not in tape_player.PLAYLISTS:
        return _error(
            "pipeline_unknown",
            404,
            f"mock-dro: no tape playlist for pipeline '{pipeline_id}' "
            f"(available: {sorted(tape_player.PLAYLISTS)})",
        )
    task = asyncio.create_task(tape_player.replay(user_id, work_id, pipeline_id, chain_id))
    task.add_done_callback(lambda t: t.exception())  # 예외 로깅 소비 (경고 억제)
    return {"chain_id": chain_id}


@app.post("/control/output", status_code=200)
async def control_output(body: dict[str, Any] = Body(...)):  # noqa: B008
    """실 /control/output 동형(C6) — docx 빌드 단발. mock 은 stateless(CM r/w 0·실 docx 없음):
    canned 응답 + RAW output_ready emit 만 → Nexus event_mapper → WS output.ready 통합 검증.
    (preview/download 200 은 dro:real 만 — mock 미영속이라 404=documented)."""
    user_id = body.get("user_id")
    work_id = body.get("work_id")
    variant = body.get("variant")
    if not (isinstance(user_id, str) and isinstance(work_id, str) and isinstance(variant, str)):
        return _error("validation_failed", 400, "control/output: user_id/work_id/variant(str) 필수")
    if variant != "draft":
        return _error(
            "validation_failed", 400, f"control/output: variant '{variant}' 미지원 (draft 만)"
        )
    payload = {"document_id": "draft", "filename": "draft.docx", "size_bytes": 2048}
    await hub.wait_subscriber(user_id, work_id)  # SSE dial race 보험 (replay 와 동형)
    await hub.emit(user_id, work_id, "output_ready", payload)
    return payload


@app.get("/events/{user_id}/{work_id}")
async def works_events(user_id: str, work_id: str) -> StreamingResponse:
    """per-session raw event SSE — 실 router 동형 헤더."""
    return StreamingResponse(
        hub.subscribe(user_id, work_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
