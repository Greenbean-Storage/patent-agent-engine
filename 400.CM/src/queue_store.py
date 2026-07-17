"""페르소나 RT 큐 — runtime/{persona}/queue.json. (P-A v3 + lease)

chain_queue 완전 폐기. chain spawn 시 producer(DRO `run_chain`)가 RT 들을 큐에 push,
(session,persona) 단일 worker 가 chain-at-a-time pop·소비 (같은 persona chain 직렬;
다른 persona·session 병렬). file-key asyncio.Lock 으로 동시 호출 직렬화.

동시성 계약 (Actor 재설계 D-1): 구 `in_flight` 단일 슬롯 폐기 — persona cap 세마포어로
같은 persona 의 RT 여러 개가 동시 실행(병렬 step·다중 세션)되므로 **rt_id 별 lease** 로 장부화.
shape = {pending: [{rt_id, chain_id, enqueued_at}],
         leases: {rt_id: {chain_id, actor, started_at, expires_at}}, updated_at}.
release 는 본인 rt_id 만 해제(타 기록 보존). 만료(expires_at) 지난 lease 는 다음 큐
작업(push/pop/release) 시 lazy 제거 — 별도 데몬 없음. expires = DRO 의 RT 시간예산 연동.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import venezia_memory as vm

from .lock import lock_for
from .store import read_by_key as read
from .store import write_by_key as write

# pop 호출이 ttl 을 명시하지 않을 때의 보수적 기본값
# (DRO 는 DISPATCH_RETRY_BUDGET_S + DISPATCH_TIMEOUT_S 를 전달).
DEFAULT_LEASE_TTL_S = 2400.0


def _now_dt() -> datetime:
    return datetime.now(UTC)


def _now() -> str:
    return _now_dt().isoformat()


# ── persona queue (RT 큐) ─────────────────────────────────────────────────────


def _queue_key(user_id: str, work_id: str, persona: int) -> str:
    return vm.queue_key(user_id, work_id, persona)


def _sweep_expired(pq: dict[str, Any]) -> None:
    """만료 lease lazy 제거 — 큐 작업(push/pop/release) 시에만 호출 (GET 은 순수)."""
    leases: dict[str, Any] = pq.get("leases") or {}
    now = _now_dt()
    for rt_id in [k for k, v in leases.items() if _expired(v, now)]:
        del leases[rt_id]
    pq["leases"] = leases


def _expired(lease: dict[str, Any], now: datetime) -> bool:
    try:
        return datetime.fromisoformat(str(lease.get("expires_at"))) <= now
    except (TypeError, ValueError):
        return True  # expires 없는/깨진 lease 는 장부 신뢰성 위해 제거


async def get_persona_queue(user_id: str, work_id: str, persona: int) -> dict[str, Any]:
    data = read(_queue_key(user_id, work_id, persona))
    if data is None:
        return {"pending": [], "leases": {}, "updated_at": _now()}
    return data


async def persona_queue_push(
    user_id: str, work_id: str, persona: int, rt_id: str, chain_id: str
) -> dict[str, Any]:
    key = _queue_key(user_id, work_id, persona)
    async with lock_for(key):
        pq = await get_persona_queue(user_id, work_id, persona)
        _sweep_expired(pq)
        pq["pending"].append({"rt_id": rt_id, "chain_id": chain_id, "enqueued_at": _now()})
        pq["updated_at"] = _now()
        write(key, pq)
        return pq


async def persona_queue_pop(
    user_id: str,
    work_id: str,
    persona: int,
    actor_id: str | None = None,
    chain_id: str | None = None,
    lease_ttl_s: float | None = None,
) -> dict[str, Any] | None:
    """pending head 를 leases 로 이동 후 반환. 큐 비어있으면 None.

    persona 큐는 같은 persona 의 여러 chain 이 공유한다(chain_queue 폐기). `chain_id`
    지정 시 그 chain 의 첫 pending 만 pop(다른 chain entry 는 보존) — 동시 다중 chain 시
    한 chain 이 다른 chain 의 RT 를 가져가 get_rt 404·오소비되는 것 방지.

    lease 는 rt_id 키로 동시 다건 공존 — persona cap 세마포어 하의 병렬 dispatch 장부.
    """
    key = _queue_key(user_id, work_id, persona)
    async with lock_for(key):
        pq = await get_persona_queue(user_id, work_id, persona)
        _sweep_expired(pq)
        pending = pq["pending"]
        if not pending:
            return None
        if chain_id is None:
            idx = 0
        else:
            idx = next((i for i, e in enumerate(pending) if e.get("chain_id") == chain_id), -1)
            if idx < 0:
                return None
        head = pending.pop(idx)
        ttl = lease_ttl_s if lease_ttl_s is not None else DEFAULT_LEASE_TTL_S
        pq["leases"][head["rt_id"]] = {
            "chain_id": head.get("chain_id"),
            "actor": actor_id,
            "started_at": _now(),
            "expires_at": (_now_dt() + timedelta(seconds=float(ttl))).isoformat(),
        }
        pq["updated_at"] = _now()
        write(key, pq)
        return head


async def persona_queue_release(
    user_id: str, work_id: str, persona: int, rt_id: str
) -> dict[str, Any]:
    """본인 rt_id 의 lease 만 해제 (타 RT 기록 보존 — 구 clear_inflight 의 오인 삭제 폐기).

    idempotent — 이미 없거나 만료 제거된 lease 는 무해.
    """
    key = _queue_key(user_id, work_id, persona)
    async with lock_for(key):
        pq = await get_persona_queue(user_id, work_id, persona)
        _sweep_expired(pq)
        pq["leases"].pop(rt_id, None)
        pq["updated_at"] = _now()
        write(key, pq)
        return pq
