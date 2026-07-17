"""DRO→Nexus per-session raw event 채널 (SSE producer).

삭제된 debug WSRegistry 대체. orchestrator 가 chain 진행 중 raw 이벤트를 `emit_raw`
로 발사 → per-(user_id, work_id) subscriber asyncio.Queue 들에 push. Nexus 가
`GET /events/{user_id}/{work_id}` (SSE) 로 dial 해 consume.

RAW only (Q7) — persona→channel·display_status 매핑은 Nexus event_mapper. 이벤트는
`(user_id, work_id)` 태그 + 키별 monotonic seq (gap 감지·dedup, Q38). replay 버퍼는
Nexus 소유 (Q9) — 여기선 보관 안 함. 구독자 없으면 best-effort drop (Q37). 큐 overflow 시
oldest drop.

계약: @contracts/00.dro/raw-sse-event.schema.json.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .sse import event as _sse_event

log = logging.getLogger(__name__)

_QUEUE_MAXSIZE = 1000


@dataclass
class _RawEventHub:
    """(user_id, work_id) → subscriber Queue 목록 + 키별 monotonic seq."""

    subscribers: dict[tuple[str, str], list[asyncio.Queue]] = field(default_factory=dict)
    _seq: dict[tuple[str, str], int] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def emit_raw(
        self,
        user_id: str,
        work_id: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        persona: int | None = None,
        step: dict[str, Any] | None = None,
    ) -> None:
        """raw 이벤트 1건을 그 키의 모든 구독자 큐에 push (seq 부여)."""
        key = (user_id, work_id)
        async with self.lock:
            seq = self._seq.get(key, 0) + 1
            self._seq[key] = seq
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
            subs = list(self.subscribers.get(key, []))
        for q in subs:
            try:
                q.put_nowait(evt)
            except asyncio.QueueFull:
                # best-effort: oldest drop 후 재시도 (Q37)
                with contextlib.suppress(asyncio.QueueEmpty, asyncio.QueueFull):
                    q.get_nowait()
                    q.put_nowait(evt)

    async def subscribe(self, user_id: str, work_id: str) -> AsyncIterator[str]:
        """per-session SSE generator. Nexus 연결 동안 raw 이벤트를 SSE 프레임으로 yield.

        연결 종료(클라 disconnect / CancelledError) 시 구독 해제.
        """
        key = (user_id, work_id)
        q: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        async with self.lock:
            self.subscribers.setdefault(key, []).append(q)
        try:
            while True:
                evt = await q.get()
                yield _sse_event(evt["type"], evt)
        finally:
            async with self.lock:
                arr = self.subscribers.get(key, [])
                self.subscribers[key] = [x for x in arr if x is not q]
                if not self.subscribers[key]:
                    self.subscribers.pop(key, None)


_hub = _RawEventHub()


async def emit_raw(
    user_id: str,
    work_id: str,
    event_type: str,
    payload: dict[str, Any],
    *,
    persona: int | None = None,
    step: dict[str, Any] | None = None,
) -> None:
    await _hub.emit_raw(user_id, work_id, event_type, payload, persona=persona, step=step)


def subscribe(user_id: str, work_id: str) -> AsyncIterator[str]:
    return _hub.subscribe(user_id, work_id)
