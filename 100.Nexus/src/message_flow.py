"""사용자 메시지 진입 흐름 (DRO orchestrator.handle_message 에서 이관, Q18=B).

Nexus 가 소유: (1) conversation user turn 기록, (2) manifest last_activity 갱신 →
DRO control 로 root chain spawn (P01 항상 + ENGINE_MODE=FULL 이면 P02). DRO 는 받은
chain 실행만 (순수 executor).

메시지 내용은 control body 에 없음 — chain composer 가 CM conversation 에서 fetch (Q34).
assistant turn 은 P01 chain 의 save step 이 append (DRO 는 conversation 의 user turn 은 안
씀 — Nexus 소유, Q21). 미디어는 메시지와 무관 (work 레벨 presigned S3 직접) — 여기서 안 다룸.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from venezia_contracts.models.dro_api.error import ErrorCode

from . import dro_client
from .cm_client import get_cm_client
from .config import P01_ENTRY, P02_ENTRY, settings
from .errors import APIError

log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def write_user_turn(
    user_id: str,
    work_id: str,
    content: str,
    correlation_id: str | None = None,
    user_turn_meta: dict[str, Any] | None = None,
) -> int:
    """work-guard 후 conversation 에 user turn **durable append**(correlation_id 멱등) → 메시지 id 반환.

    멱등 경계의 '확정 가능' 단계 — guard(미존재 work → APIError) + append 만(빠르고 원자적).
    correlation_id 를 turn meta 에 실으면 CM 이 멱등 append(같은 corr 재처리 시 기존 turn id 반환,
    중복 0). manifest 갱신·chain spawn 은 `spawn_root_chains` 로 분리(느린 best-effort).
    반환 = user turn 의 메시지 id(= conversation 내 0-based 위치, A-4 server id).
    """
    cm = get_cm_client()
    # 방어적 work-guard (쓰기측): 없는 work 에 orphan turn/runtime 생성 방지.
    # WS 는 connect 에서 이미 거르지만(belt-and-suspenders), REST roadmap_submit 경로도 보호.
    if await cm.get_context_manifest(user_id, work_id) is None:
        raise APIError(ErrorCode.work_not_found, 404, f"work '{work_id}' not found")
    meta: dict[str, Any] = dict(user_turn_meta or {})
    if correlation_id is not None:
        meta["correlation_id"] = correlation_id  # CM 멱등 append 키 (turn 중복 방지)
    user_turn: dict[str, Any] = {"role": "user", "content": content, "timestamp": _now()}
    if meta:
        user_turn["meta"] = meta
    return await cm.append_conversation(user_id, work_id, user_turn)


def _chain_id_for(work_id: str, correlation_id: str | None, persona: int) -> str:
    """root chain_id — correlation_id 가 있으면 **결정적**(uuid5), 없으면(REST roadmap) 랜덤.

    결정적이면 같은 message.send 재시도/재-spawn 이 **같은 chain_id** 를 써서 DRO 의 멱등 admission(I1:
    같은 chain_id 면 drop)이 중복 실행을 차단 — 원 spawn 이 실패했으면 재시도가 그 chain 을 비로소 생성,
    성공했으면 drop. 처리 안 된 turn 의 ack 잔재(W5) 해소의 핵심.
    """
    if not correlation_id:
        return str(uuid.uuid4())
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{work_id}:{correlation_id}:p{persona}"))


async def spawn_root_chains(
    user_id: str, work_id: str, correlation_id: str | None = None
) -> None:
    """P01.R00 + (FULL 이면) P02.R00 root chain spawn + manifest last_activity 갱신.

    chain_id 는 correlation_id 에서 **결정적** 도출 → 같은 message.send 재처리 시 같은 id 로 재-spawn
    하면 DRO I1 admission 이 멱등(원 실패는 완결, 성공은 drop). 매 send 경로(신규·done replay)에서
    호출해도 안전 — 두 chain 은 평행(다른 persona worker).
    """
    cm = get_cm_client()
    await cm.patch_context_manifest(
        user_id, work_id, [{"op": "add", "path": "/last_activity_at", "value": _now()}]
    )
    # DRO control 로 root chain spawn (trigger 최소 — 내용은 CM, Q34).
    p01_pid, p01_persona = P01_ENTRY
    await dro_client.control_spawn(
        user_id,
        work_id,
        p01_persona,
        p01_pid,
        _chain_id_for(work_id, correlation_id, p01_persona),
        {"kind": "user_message"},
    )
    if settings.ENGINE_MODE.upper() == "FULL":
        p02_pid, p02_persona = P02_ENTRY
        await dro_client.control_spawn(
            user_id,
            work_id,
            p02_persona,
            p02_pid,
            _chain_id_for(work_id, correlation_id, p02_persona),
            {"kind": "user_message"},
        )


async def handle_message(
    user_id: str,
    work_id: str,
    content: str,
    user_turn_meta: dict[str, Any] | None = None,
) -> int:
    """비멱등 편의 래퍼 (REST roadmap_submit 용): user turn write + root chain spawn 일괄.

    멱등 경계가 필요한 WS message.send 는 write_user_turn / spawn_root_chains 를 분리 호출한다.
    반환 = user turn 메시지 id. 미디어는 메시지와 무관(work 레벨 presigned S3 직접).
    """
    message_id = await write_user_turn(user_id, work_id, content, user_turn_meta=user_turn_meta)
    await spawn_root_chains(user_id, work_id)
    return message_id
