"""client WS inbound (client→server) parser + dispatcher.

router.py 의 WS endpoint 가 receive_text 로 받은 JSON 을 위임. inbound action **1종**(strict, A-4):
  - "message.send" → 클라 `correlation_id`(멱등키) + content. message_flow.handle_message 후
    message.received ack(unicast, data={correlation_id, id}). 재시도 = **같은 correlation_id 로
    재send**(서버가 멱등 dedup) — 별도 message.resend 액션 없음.

멱등 계약(완전, A-4): 같은 correlation_id 재수신 = 원결과 재-ack(새 turn/spawn 0), 같은 id +
다른 content = system.error(conflict). 범위 = work(키 `message:{work_id}:{correlation_id}`).
dedup = CM idempotency store(claim/put, 단일 인스턴스 원자) — 내용비교 폐기.

봉투 = {type, timestamp, seq, data}. system.error / message.received 는 호출 소켓에 직접 unicast
(registry 우회). 진실 = CM(이벤트는 best-effort). strict 위반은 system.error(ErrorCode).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket
from venezia_contracts.models.dro_api.error import ErrorCode

from . import message_flow
from .cm_client import get_cm_client
from .errors import APIError

log = logging.getLogger(__name__)

_PROC_ERROR_MSG = "메시지 처리 중 오류 — 다시 시도해 주세요."


async def _send_direct(ws: WebSocket, event_type: str, data: dict[str, Any]) -> None:
    """envelope v2 단일 socket 직접 send (registry 우회 — 호출자에게만). seq=0 (replay 미적재)."""
    await ws.send_json(
        {
            "type": event_type,
            "timestamp": datetime.now(UTC).isoformat(),
            "seq": 0,
            "data": data,
        }
    )


async def _error(ws: WebSocket, code: ErrorCode, message: str) -> None:
    await _send_direct(ws, "system.error", {"code": code.value, "message": message})


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def _validate_send_frame(msg: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    """strict: msg = {action, data} 만, data = {content(str, non-empty), correlation_id(str)} 만.
    반환 (content, correlation_id, None) 성공 / (None, None, error_message) 실패."""
    extra = set(msg) - {"action", "data"}
    if extra:
        return None, None, f"unexpected fields {sorted(extra)}"
    data = msg.get("data")
    if not isinstance(data, dict):
        return None, None, "data must be an object"
    d_extra = set(data) - {"content", "correlation_id"}
    if d_extra:
        return None, None, f"unexpected data fields {sorted(d_extra)}"
    content = data.get("content")
    if not isinstance(content, str) or not content.strip():
        return None, None, "content (non-empty string) required"
    corr = data.get("correlation_id")
    if not isinstance(corr, str) or not corr.strip():
        return None, None, "correlation_id (string) required"
    return content.strip(), corr.strip(), None


async def handle_inbound(websocket: WebSocket, raw: str, user_id: str, work_id: str) -> None:
    """단일 inbound frame 처리."""
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError as exc:
        await _error(websocket, ErrorCode.validation_failed, f"invalid JSON: {exc}")
        return
    if not isinstance(msg, dict):
        await _error(websocket, ErrorCode.validation_failed, "frame must be an object")
        return

    action = msg.get("action")
    if action == "message.send":
        await _handle_message_send(websocket, msg, user_id, work_id)
        return

    await _error(
        websocket, ErrorCode.validation_failed, f"unknown action: {action!r} (message.send 만 지원)"
    )


async def _handle_message_send(
    websocket: WebSocket, msg: dict[str, Any], user_id: str, work_id: str
) -> None:
    """멱등 message.send: correlation_id 로 dedup → 신규만 처리, ack(data={correlation_id, id})."""
    content, correlation_id, err = _validate_send_frame(msg)
    if content is None or correlation_id is None:
        await _error(websocket, ErrorCode.validation_failed, f"message.send: {err}")
        return

    cm = get_cm_client()
    key = f"message:{work_id}:{correlation_id}"
    content_hash = _content_hash(content)
    try:
        state, rec = await cm.claim_idempotency(user_id, key, content_hash)
    except Exception:
        log.exception("claim_idempotency failed user=%s work=%s", user_id, work_id)
        await _error(websocket, ErrorCode.internal, _PROC_ERROR_MSG)
        return

    # done = 이미 처리 완료(put 이 spawn 성공 후) → 재-spawn 없이 재-ack. 재-spawn 은 원 spawn 이
    # DRO coalesce 로 흡수(미생성)됐을 때 중복 chain 을 만들 수 있어 done 에서는 금지.
    if state == "done":
        rec = rec or {}
        if rec.get("content_hash") != content_hash:
            await _error(
                websocket, ErrorCode.conflict, "correlation_id reused with different content"
            )
            return
        await _emit_accepted(websocket, correlation_id, (rec.get("body") or {}).get("message_id"))
        return

    # in_flight = 동시 처리 중 또는 직전 크래시(미완·미확정). 충돌만 검사하고 **claimed 와 동일하게
    # 멱등 재처리** 로 진행 — stale in-flight(원 핸들러가 spawn 전 죽음)도 결국 spawn 되어 완결되며,
    # write 는 CM correlation_id 멱등(turn 중복 0)·spawn 은 결정적 chain_id DRO I1 멱등(chain 중복 0)
    # 이라 동시/재처리해도 안전. (heart-ack 만 하고 미처리로 남는 일 없음.)
    if state == "in_flight" and (rec or {}).get("content_hash") != content_hash:
        await _error(
            websocket, ErrorCode.conflict, "correlation_id reused with different content"
        )
        return

    # claimed(신규/TTL 재선점) 또는 in_flight(충돌 아님) → write_user_turn(correlation_id 로 CM 멱등
    # append — 재처리해도 turn 중복 0) → spawn → put(done). 어떤 단계 실패든 **선점 해제** 해 재시도가
    # 처음부터 재처리(CM 멱등 write + 결정적 chain_id DRO I1 이 중복 차단). put(done)은 spawn 성공 후.
    try:
        message_id = await message_flow.write_user_turn(
            user_id=user_id, work_id=work_id, content=content, correlation_id=correlation_id
        )
    except APIError as exc:
        await cm.delete_idempotency(user_id, key)
        await _error(websocket, exc.code, exc.message)
        return
    except Exception:
        await cm.delete_idempotency(user_id, key)
        log.exception("write_user_turn failed user=%s work=%s", user_id, work_id)
        await _error(websocket, ErrorCode.internal, _PROC_ERROR_MSG)
        return

    # root chain spawn — 결정적 chain_id(correlation_id 도출). spawn 실패 시 선점 해제 → 재시도가
    # 같은 chain_id 로 재-spawn(원 실패면 완결, 원 성공이면 DRO I1 drop) + turn 은 CM 멱등이라 중복 0.
    try:
        await message_flow.spawn_root_chains(
            user_id=user_id, work_id=work_id, correlation_id=correlation_id
        )
    except Exception:
        await cm.delete_idempotency(user_id, key)  # done 으로 확정 안 함 → 재시도가 재처리해 완결
        log.exception("spawn_root_chains failed user=%s work=%s", user_id, work_id)
        await _error(websocket, ErrorCode.internal, _PROC_ERROR_MSG)
        return

    # spawn 성공 후 done 확정 → done-replay 는 재-spawn 없이 ack 만(중복 chain 0). put 실패 시 claim
    # 은 claimed 유지 → 재시도가 멱등 재처리(write CM dedup + spawn I1).
    try:
        await cm.put_idempotency(
            user_id, key, {"body": {"message_id": message_id}, "content_hash": content_hash}
        )
    except Exception:  # noqa: BLE001
        log.warning("put_idempotency failed user=%s work=%s (turn 저장됨)", user_id, work_id)
    await _emit_accepted(websocket, correlation_id, message_id)


async def _emit_accepted(
    websocket: WebSocket, correlation_id: str, message_id: int | None
) -> None:
    """message.received — server acceptance ack (unicast). data = {correlation_id, id}.

    id = 저장된 user turn 의 메시지 id(A-4 server id). 동시중복(in_flight)은 id=null.
    후속 chain 완료를 보장하는 ack 는 아니다(best-effort, 진실=CM)."""
    await _send_direct(
        websocket, "message.received", {"correlation_id": correlation_id, "id": message_id}
    )
