"""DRO 내부 control + event 표면 (Nexus 게이트웨이 전용 — 외부 비노출).

DRO 는 순수 체인 실행기 (sub-plan ② 코어 컷오버). 외부 클라이언트 표면 0 —
모든 client REST/WS 는 Nexus 소유. DRO REST = {control/spawn, control/output, events, health}.

  POST /control/spawn — Nexus→DRO: 체인 실행 요청. {user_id, work_id, persona,
      pipeline_id, chain_id, trigger?} → 202 {chain_id}. 인증 없음 (내부망 신뢰, Q32).
      user_id 평문 (JWT 아님, Q34). run_chain facade 호출 → producer 가 RT enqueue + worker 깨움.
  POST /control/output — Nexus→DRO: IOM → 출원서 docx 빌드 (C6). {user_id, work_id, variant}
      → 200 {document_id, filename, size_bytes}. AI 없는 단발 동기 변환 — chain 불요.
      IOM CM fetch → PatentDocxGenerator in-process → CM outputs upload → RAW output_ready emit.
      variant="draft" 만 (proposal 은 Nexus 가 501, DRO 미처리).
  GET  /events/{user_id}/{work_id} — DRO→Nexus per-session SSE.
      RAW 진행 이벤트 stream (event_sse). Nexus 가 dial → event_mapper 로 가공 → client WS.

계약: @contracts/00.dro/{control-spawn-request,control-spawn-response,raw-sse-event}.schema.json.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Body
from fastapi.responses import StreamingResponse
from venezia_contracts.models.dro_api.error import ErrorCode

from . import event_sse
from .cm_client import get_cm_client
from .docx_generator import PatentDocxGenerator
from .errors import APIError
from .pipeline_walker import AmbiguousPipelineId, resolve_pipeline_id
from .worker import run_chain

log = logging.getLogger(__name__)
router = APIRouter()

_DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@router.post("/control/spawn", status_code=202)
async def control_spawn(body: dict[str, Any] = Body(...)) -> dict[str, str]:
    """Nexus→DRO 체인 실행 요청. chain_id 는 Nexus 발급 (media/turn/conversation 선기록)."""
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
        raise APIError(
            ErrorCode.validation_failed,
            400,
            "control/spawn: user_id/work_id/pipeline_id/chain_id(str) + persona(int) 필수",
        )
    # persona 범위 — 계약(control-spawn-request: 1-6)을 경계에서 강제. 구: 범위 밖이
    # run_chain 깊은 곳 RuntimeError→500 으로 샜음. 4xx fail-loud 와 동일 400 (I2).
    if not 1 <= persona <= 6:
        raise APIError(
            ErrorCode.validation_failed, 400, f"control/spawn: persona {persona} 범위 밖 (1-6)"
        )
    # short-form(P{NN}.R{NN}) → full id 해소 + 존재 검증을 받자마자(202 전) 수행.
    # 이렇게 안 하면 미존재/short-form pipeline 이 background worker(run_chain)의 load_pipeline
    # 에서 조용히 죽음 — 그 자리에서 4xx 로 fail-loud. (run_chain 도 재resolve, idempotent)
    try:
        pipeline_id = resolve_pipeline_id(pipeline_id)
    except AmbiguousPipelineId as e:
        raise APIError(ErrorCode.pipeline_ambiguous, 409, str(e)) from e
    except KeyError as e:
        raise APIError(
            ErrorCode.pipeline_unknown, 404, f"pipeline '{pipeline_id}' not found"
        ) from e
    raw_trigger = body.get("trigger")
    trigger = raw_trigger if isinstance(raw_trigger, dict) else {"kind": "control_spawn"}
    # run_chain facade (A-4): producer 가 RT enqueue + worker 깨움. chain_id 는 Nexus 발급(유지).
    await run_chain(
        user_id, work_id, pipeline_id, persona=persona, chain_id=chain_id, trigger=trigger
    )
    return {"chain_id": chain_id}


@router.post("/control/output", status_code=200)
async def control_output(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Nexus→DRO: IOM → 출원서 docx 빌드 (C6 — output/docx 재배선).

    AI 없는 단발 동기 변환 — chain 불요(파이프라인·RT·worker 미경유). IOM 을 CM 에서 읽어
    PatentDocxGenerator 로 in-process 합성 → CM outputs 에 draft.docx upload → RAW output_ready
    1건 발사(Nexus event_mapper 가 client WS output.ready 로 매핑). 동기 응답=빌드 확인,
    WS 알림은 비동기(best-effort, #15). variant="draft" 만 — proposal 은 Nexus 가 501.
    """
    user_id = body.get("user_id")
    work_id = body.get("work_id")
    variant = body.get("variant")
    if not (isinstance(user_id, str) and isinstance(work_id, str) and isinstance(variant, str)):
        raise APIError(
            ErrorCode.validation_failed, 400, "control/output: user_id/work_id/variant(str) 필수"
        )
    if variant != "draft":
        raise APIError(
            ErrorCode.validation_failed,
            400,
            f"control/output: variant '{variant}' 미지원 (draft 만)",
        )
    cm = get_cm_client()
    iom = await cm.get_iom(user_id, work_id)
    if iom is None:
        raise APIError(
            ErrorCode.content_not_ready, 404, "작성 콘텐츠 미준비 — 구체화 단계 진행 후 재시도"
        )
    drawing_manifest = await cm.get_drawing_manifest(user_id, work_id)
    # 동기 docx 빌드(수백 줄, blocking)를 to_thread 로 오프로드 — 단일 이벤트 루프가 전 chain
    # worker·SSE 구독을 구동하므로 큰 IOM 빌드가 루프를 멈추지 않도록 (I3).
    docx = await asyncio.to_thread(
        lambda: PatentDocxGenerator().generate(iom, drawing_manifest).getvalue()
    )
    await cm.upload_document(user_id, work_id, "draft.docx", docx, content_type=_DOCX_MEDIA_TYPE)
    payload = {"document_id": "draft", "filename": "draft.docx", "size_bytes": len(docx)}
    # RAW output_ready 발사 — Nexus event_mapper 가 client WS output.ready 로 매핑 (채널 미부여).
    await event_sse.emit_raw(user_id, work_id, "output_ready", payload)
    return payload


@router.get("/events/{user_id}/{work_id}")
async def works_events(user_id: str, work_id: str) -> StreamingResponse:
    """per-session raw event SSE (DRO→Nexus). Nexus 가 client WS 세션마다 1개 dial."""
    return StreamingResponse(
        event_sse.subscribe(user_id, work_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
