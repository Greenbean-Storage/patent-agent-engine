"""DRO raw SSE 이벤트 → client WS 이벤트 (envelope v2 {type,timestamp,seq,data}) 매핑.

  rt_started                 → work.progress {display_status, channel}  (모든 RT 시작)
  chain_completed(persona=1) → message.reply {text}  (CM 최신 assistant turn, chain 완료당 1회)
  chain_completed(persona=2) → model.maturity + model.roadmap {count}  (CM fetch, DRO 미발사)
  output_ready               → output.ready {document_id, filename, size_bytes, +urls}  (C6)
  rt_error / error           → work.failed {message, channel}  (broadcast, 사용자 안전 sanitize)
  rt_enqueued/rt_progress/rt_result → 사용자 미노출 (내부 관측)

이벤트는 best-effort 알림 — 진실은 CM, refresh 로 복구. 모델신호·답장은 Nexus 가 CM 에서 생성.
work.failed 의 message 는 일반 문구(내부 예외/persona/chain id 비노출), raw 는 log 에만.
"""

from __future__ import annotations

import logging
from typing import Any

from venezia_contracts.models.dro_api.channels import PERSONA_TO_CHANNEL

from .cm_client import get_cm_client
from .routes import output_draft_preview_url, output_draft_url
from .ws_manager import get_production_ws_registry

log = logging.getLogger(__name__)

_FALLBACK_STATUS_KO = "진행 중…"
_FALLBACK_STATUS_EN = "Working…"
_FALLBACK_CHANNEL = "support"


def _channel_for_persona(persona: int | None) -> str:
    if persona is None:
        return _FALLBACK_CHANNEL
    return PERSONA_TO_CHANNEL.get(persona, _FALLBACK_CHANNEL)


def _display_status_from_step(step: dict[str, Any] | None) -> dict[str, str]:
    if not step:
        return {"ko": _FALLBACK_STATUS_KO, "en": _FALLBACK_STATUS_EN}
    ds = step.get("display_status")
    if isinstance(ds, dict) and isinstance(ds.get("ko"), str):
        return {"ko": ds["ko"], "en": ds.get("en") or _FALLBACK_STATUS_EN}
    return {"ko": _FALLBACK_STATUS_KO, "en": _FALLBACK_STATUS_EN}


def _latest_assistant(conv: Any) -> tuple[int | None, str | None]:
    """conversation 최신 assistant turn 의 (메시지 id = 0-based 위치, content). meta 비노출 (A-4).

    CM 의 get_conversation 은 dict `{"messages":[...], ...}` 반환 (list 아님) — messages 언랩.
    """
    msgs = conv.get("messages") if isinstance(conv, dict) else None
    if not isinstance(msgs, list):
        return None, None
    for i in range(len(msgs) - 1, -1, -1):
        turn = msgs[i]
        if isinstance(turn, dict) and turn.get("role") == "assistant":
            c = turn.get("content")
            return i, (c if isinstance(c, str) else None)
    return None, None


async def _emit(user_id: str, work_id: str, event_type: str, data: dict) -> None:
    await get_production_ws_registry().emit_business(user_id, work_id, event_type, data)


# work.failed 의 사용자 안전 메시지 — 내부 예외/persona/chain id 노출 금지(메타 비식별).
# raw payload(내부 디테일)는 log 에만, 사용자엔 항상 이 일반 문구.
_FAILED_MESSAGE = "처리 중 오류가 발생했어요. 잠시 후 다시 시도해 주세요."


async def handle_raw_event(raw: dict[str, Any]) -> None:
    """DRO→Nexus raw SSE 이벤트 1건 → client WS 비즈니스 이벤트 broadcast.

    raw = {type, user_id, work_id, persona, seq, timestamp, payload, step?}.
    """
    user_id = raw.get("user_id")
    work_id = raw.get("work_id")
    if not isinstance(user_id, str) or not isinstance(work_id, str):
        log.debug("event_mapper.skip — missing user_id/work_id: %s", raw.get("type"))
        return
    rtype = raw.get("type")
    _s = raw.get("step")
    step: dict[str, Any] | None = _s if isinstance(_s, dict) else None
    _persona = raw.get("persona")
    persona: int | None = _persona if isinstance(_persona, int) else None

    if rtype == "rt_started":
        # 모든 RT 시작 시 그 step 의 사용자 문구를 progress 로
        # (#6 — Nexus 순수 전달 + persona→channel 카테고리).
        await _emit(
            user_id,
            work_id,
            "work.progress",
            {
                "display_status": _display_status_from_step(step),
                "channel": _channel_for_persona(persona),
            },
        )
    elif rtype == "chain_completed":
        cm = get_cm_client()
        if persona == 1:
            # 응대 답장 = CM conversation 최신 assistant turn content (메타 비노출, 1회/메시지).
            conv = await cm.get_conversation(user_id, work_id)
            reply_id, reply_text = _latest_assistant(conv)
            await _emit(user_id, work_id, "message.reply", {"id": reply_id, "text": reply_text})
        elif persona == 2:
            # 모델 신호 = Nexus 가 CM fetch 로 생성 (#12 — DRO 미발사).
            # 빈값(예 dro:fake) 이면 미발생.
            maturity = await cm.get_concept_maturity_model(user_id, work_id)
            if isinstance(maturity, dict):
                await _emit(
                    user_id,
                    work_id,
                    "model.maturity",
                    {
                        "overall_score": maturity.get("overall_score") or 0.0,
                        "scores": maturity.get("scores") or {},
                        "weights": maturity.get("weights") or {},
                    },
                )
            roadmap = await cm.get_user_roadmap(user_id, work_id)
            if isinstance(roadmap, list):
                await _emit(user_id, work_id, "model.roadmap", {"count": len(roadmap)})
    elif rtype == "output_ready":
        # 문서 빌드 완료 신호 (C6 — DRO POST /control/output 발사). client URL 은 Nexus 만 아는
        # 표면 — document_id 로 preview/download 경로 enrich (raw 의 3 필수 필드 + optional URL 2).
        raw_payload = raw.get("payload")
        payload = raw_payload if isinstance(raw_payload, dict) else {}
        doc_id = payload.get("document_id")
        await _emit(
            user_id,
            work_id,
            "output.ready",
            {
                "document_id": doc_id,
                "filename": payload.get("filename"),
                "size_bytes": payload.get("size_bytes"),
                "preview_url": output_draft_preview_url(work_id),
                "download_url": output_draft_url(work_id),
            },
        )
    elif rtype in ("rt_error", "error"):
        # work 처리 실패 → 사용자에 알림 (work.failed, broadcast). 메시지는 사용자 안전 문구로
        # sanitize(메타 비식별) — raw payload(내부 예외 등)는 log 에만 (#17 fail-loud 내부).
        _rp = raw.get("payload")
        log.warning(
            "event_mapper.work_failed type=%s persona=%s payload=%s",
            rtype,
            persona,
            _rp if isinstance(_rp, dict) else None,
        )
        await _emit(
            user_id,
            work_id,
            "work.failed",
            {"message": _FAILED_MESSAGE, "channel": _channel_for_persona(persona)},
        )
    else:
        # rt_enqueued/rt_progress/rt_result → 사용자 미노출 (내부 관측 #15).
        log.debug("event_mapper.internal_raw type=%s persona=%s", rtype, persona)
