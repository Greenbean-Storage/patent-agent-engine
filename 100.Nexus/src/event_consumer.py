"""per-session DRO→Nexus SSE consumer → client WS fan-out (ref-counted lifecycle).

sub-plan ② — client WS 가 (user_id, work_id) 키로 연결되면 그 키의 DRO SSE 를 1개
dial. 같은 키의 멀티탭(여러 WS connection)은 SSE consumer 1개를 공유(ref-count) — 마지막
WS disconnect 시 consumer cancel (orphan 스트림 방지). SSE→내부 asyncio.Queue 버퍼(Q9 —
backpressure·버스트 흡수) → event_mapper 가 envelope v2 로 매핑 + ws_manager broadcast.
SSE 끊김 시 세션이 살아있는 동안 재연결(best-effort, Q37).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass

from . import dro_client, event_mapper

log = logging.getLogger(__name__)

_QUEUE_MAXSIZE = 1000
_RECONNECT_DELAY_S = 1.0


@dataclass
class _Session:
    task: asyncio.Task
    refcount: int = 0
    queue_drops: int = 0  # SSE 버스트로 큐 overflow 시 유실 건수 (관측성, C3)


class _ConsumerManager:
    def __init__(self) -> None:
        self._sessions: dict[tuple[str, str], _Session] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, user_id: str, work_id: str) -> None:
        """client WS 연결 시 호출 — 키별 SSE consumer 시작(없으면) + ref +1."""
        key = (user_id, work_id)
        async with self._lock:
            s = self._sessions.get(key)
            if s is None:
                task = asyncio.create_task(
                    self._run(user_id, work_id), name=f"sse:{user_id}:{work_id}"
                )
                s = _Session(task=task, refcount=0)
                self._sessions[key] = s
            s.refcount += 1

    async def release(self, user_id: str, work_id: str) -> None:
        """client WS 해제 시 호출 — ref -1, 0 이면 SSE consumer cancel."""
        key = (user_id, work_id)
        async with self._lock:
            s = self._sessions.get(key)
            if s is None:
                return
            s.refcount -= 1
            if s.refcount <= 0:
                s.task.cancel()
                self._sessions.pop(key, None)

    async def _run(self, user_id: str, work_id: str) -> None:
        queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        producer = asyncio.create_task(self._produce(user_id, work_id, queue))
        try:
            while True:
                raw = await queue.get()
                try:
                    await event_mapper.handle_raw_event(raw)
                except Exception:  # noqa: BLE001
                    log.exception("event_consumer.map_failed")
        finally:
            producer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await producer

    async def _produce(self, user_id: str, work_id: str, queue: asyncio.Queue) -> None:
        """DRO SSE 를 재연결하며 소비 → 큐 push (overflow=oldest drop + 유실 계측, Q37·C3)."""
        key = (user_id, work_id)
        while True:
            try:
                async for raw in dro_client.consume_events(user_id, work_id):
                    try:
                        queue.put_nowait(raw)
                    except asyncio.QueueFull:
                        # overflow — oldest drop (best-effort). 유실 계측(관측성, C3).
                        s = self._sessions.get(key)
                        if s is not None:
                            s.queue_drops += 1
                        log.warning(
                            "event_consumer.queue_drop user=%s inv=%s drops=%s "
                            "(SSE 버스트 → 이벤트 유실; client refresh 로 복구 #15)",
                            user_id,
                            work_id,
                            s.queue_drops if s is not None else "?",
                        )
                        with contextlib.suppress(asyncio.QueueEmpty, asyncio.QueueFull):
                            queue.get_nowait()
                            queue.put_nowait(raw)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("event_consumer.sse_error user=%s inv=%s: %s", user_id, work_id, e)
            await asyncio.sleep(_RECONNECT_DELAY_S)


_manager = _ConsumerManager()


async def acquire(user_id: str, work_id: str) -> None:
    await _manager.acquire(user_id, work_id)


async def release(user_id: str, work_id: str) -> None:
    await _manager.release(user_id, work_id)
