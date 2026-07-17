"""per-(user_id, work_id) RAW event hub — 실 `src/event_sse.py:_RawEventHub` 미러.

emit 시점에 seq(per-key monotonic) + timestamp 를 할당한다 (tape 에 박지 않음 —
engine=full 의 P01+P02 두 chain 이 한 키를 공유하므로 hard-coded seq 면 충돌).
구독자 없으면 best-effort drop, 큐 overflow 시 oldest drop (실 DRO parity).
`wait_subscriber` 는 spawn↔SSE-dial race 보험 — Nexus 는 client WS 연결 시점에 dial
하므로 실제로는 항상 선행하지만, mock 은 즉시 재생이라 짧은 대기를 둔다.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from .sse import event as _sse_event

_QUEUE_MAXSIZE = 1000

_subscribers: dict[tuple[str, str], list[asyncio.Queue]] = {}
_seq: dict[tuple[str, str], int] = {}
_lock = asyncio.Lock()


async def emit(
    user_id: str,
    work_id: str,
    event_type: str,
    payload: dict[str, Any],
    *,
    persona: int | None = None,
    step: dict[str, Any] | None = None,
) -> None:
    """raw 이벤트 1건 — seq/timestamp 할당 후 그 키의 모든 구독자 큐에 push."""
    key = (user_id, work_id)
    async with _lock:
        seq = _seq.get(key, 0) + 1
        _seq[key] = seq
        evt: dict[str, Any] = {
            "type": event_type,
            "user_id": user_id,
            "work_id": work_id,
            "persona": persona,
            "seq": seq,
            "timestamp": datetime.now(UTC).isoformat(),
            "payload": payload,
        }
        if step is not None:
            evt["step"] = {
                "id": step.get("id"),
                "display_status": step.get("display_status"),
            }
        subs = list(_subscribers.get(key, []))
    for q in subs:
        try:
            q.put_nowait(evt)
        except asyncio.QueueFull:
            with contextlib.suppress(asyncio.QueueEmpty, asyncio.QueueFull):
                q.get_nowait()
                q.put_nowait(evt)


async def subscribe(user_id: str, work_id: str) -> AsyncIterator[str]:
    """per-session SSE generator — 무한 q.get (tape 소진 후에도 연결 유지, 실 DRO 동일)."""
    key = (user_id, work_id)
    q: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
    async with _lock:
        _subscribers.setdefault(key, []).append(q)
    try:
        while True:
            evt = await q.get()
            yield _sse_event(evt["type"], evt)
    finally:
        async with _lock:
            arr = _subscribers.get(key, [])
            _subscribers[key] = [x for x in arr if x is not q]
            if not _subscribers[key]:
                _subscribers.pop(key, None)


async def wait_subscriber(user_id: str, work_id: str, timeout: float = 2.0) -> bool:
    """그 키의 구독자가 생길 때까지 짧게 대기. timeout 이면 False (그냥 재생 = drop)."""
    key = (user_id, work_id)
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        async with _lock:
            if _subscribers.get(key):
                return True
        await asyncio.sleep(0.05)
    return False
