"""Client WebSocket connection registry — server→client push (envelope v2).

sub-plan ② 코어 컷오버로 DRO 에서 Nexus 로 이관 (production 채널만, debug v1 제거).
Nexus 가 유일한 client WS 서버 — DRO→Nexus raw SSE → event_mapper 가공 → 이 registry 로
broadcast. 키 = (user_id, work_id). in-memory (Q9 — 다중 Nexus 영속은 강건화 future).

봉투: {type, timestamp, seq, data} (scope·subject_id 없음 — 연결이 (user_id, work_id) 별).
seq 는 키별 monotonic (모든 connection 공유) — replay buffer(200) 로 재연결 since_seq replay.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket

_REPLAY_BUFFER_SIZE = 200

log = logging.getLogger(__name__)


@dataclass
class WSConnection:
    websocket: WebSocket
    seq: int = 0


@dataclass
class WSRegistry:
    """(user_id, work_id) → 연결된 WebSocket 목록 + replay buffer."""

    connections: dict[tuple[str, str], list[WSConnection]] = field(default_factory=dict)
    replay: dict[tuple[str, str], deque] = field(default_factory=dict)
    _seq_per_key: dict[tuple[str, str], int] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def add(self, user_id: str, work_id: str, ws: WebSocket) -> int:
        """연결 등록. 등록 후 그 키의 connection 수 반환 (event_consumer ref-count 용)."""
        async with self.lock:
            arr = self.connections.setdefault((user_id, work_id), [])
            arr.append(WSConnection(ws))
            return len(arr)

    def _gc_locked(self, key: tuple[str, str]) -> None:
        """마지막 연결 해제 시 키의 connections/replay/seq GC (lock 보유 중 — 메모리 bound).
        재연결은 빈 버퍼 → replay_since 가 system.resync_required 발사 (C1+C3 합성)."""
        self.connections.pop(key, None)
        self.replay.pop(key, None)
        self._seq_per_key.pop(key, None)

    async def remove(self, user_id: str, work_id: str, ws: WebSocket) -> int:
        """연결 해제. 해제 후 남은 connection 수 반환 (0 이면 키 GC)."""
        key = (user_id, work_id)
        async with self.lock:
            arr = [c for c in self.connections.get(key, []) if c.websocket is not ws]
            if arr:
                self.connections[key] = arr
            else:
                self._gc_locked(key)
            return len(arr)

    async def _prune_dead(self, user_id: str, work_id: str, dead: list[WSConnection]) -> None:
        if not dead:
            return
        key = (user_id, work_id)
        async with self.lock:
            live = [c for c in self.connections.get(key, []) if c not in dead]
            if live:
                self.connections[key] = live
            else:
                self._gc_locked(key)

    async def emit_business(
        self,
        user_id: str,
        work_id: str | None,
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        """envelope v2 broadcast. seq 는 키별 monotonic, replay buffer 에 push.
        봉투 = {type, timestamp, seq, data} (scope·subject_id 없음 — 연결이 work별)."""
        key = (user_id, work_id or "")
        ts = datetime.now(UTC).isoformat()
        async with self.lock:
            seq = self._seq_per_key.get(key, 0) + 1
            self._seq_per_key[key] = seq
            payload = {
                "type": event_type,
                "timestamp": ts,
                "seq": seq,
                "data": data,
            }
            buf = self.replay.setdefault(key, deque(maxlen=_REPLAY_BUFFER_SIZE))
            buf.append(payload)
            conns = list(self.connections.get(key, []))
        dead: list[WSConnection] = []
        for conn in conns:
            try:
                await conn.websocket.send_json(payload)
            except Exception:  # noqa: BLE001
                dead.append(conn)
        await self._prune_dead(user_id, work_id or "", dead)

    async def _send_resync(self, ws: WebSocket, reason: str) -> None:
        """system.resync_required unicast (죽은 소켓이면 조용히 — best-effort)."""
        with contextlib.suppress(Exception):
            await ws.send_json(
                {
                    "type": "system.resync_required",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "seq": 0,
                    "data": {"reason": reason},
                }
            )

    async def replay_since(self, user_id: str, work_id: str, ws: WebSocket, since_seq: int) -> None:
        """재연결 replay. buffer evict / 빈 버퍼 재연결(소실) 시 system.resync_required.

        since_seq==0 = fresh 또는 replay-all → 보낼 것 없으면 no-op (resync 불요).
        """
        key = (user_id, work_id)
        async with self.lock:
            buf = list(self.replay.get(key, ()))
        if not buf:
            # 빈 버퍼 + client 가 이전 seq 보유 = 재연결인데 버퍼 소실(C1 GC/서버 재시작) → resync.
            if since_seq > 0:
                await self._send_resync(ws, f"empty buffer (req={since_seq})")
            return
        oldest_seq = buf[0]["seq"]
        newest_seq = buf[-1]["seq"]
        if since_seq > newest_seq:
            # client seq 가 우리 newest 보다 큼 = 카운터 리셋(GC 후 재연결 + 신규 emit) → 정합 깨짐.
            await self._send_resync(ws, f"seq reset (newest={newest_seq}, req={since_seq})")
            return
        if since_seq < oldest_seq - 1:
            await self._send_resync(ws, f"buffer evicted (oldest={oldest_seq}, req={since_seq})")
            return
        for ev in buf:
            if ev["seq"] > since_seq:
                try:
                    await ws.send_json(ev)
                except Exception:  # noqa: BLE001
                    return


_production_registry = WSRegistry()


def get_production_ws_registry() -> WSRegistry:
    return _production_registry
