"""동시성 슬롯 — persona 별 + tool 풀 분리 (engine.config cap 집행).

구 "1 컨테이너 = 1 작업" 전역 busy 1-slot 폐기 (Actor 재설계 A2·B-1·D-3).
- persona 풀: dispatch 동시 수 = engine.config personas.{id}.max_concurrency.
- tool 풀: POST /tool 동시 수 = engine.config tools.max_concurrency — dispatch 와 비공유.
- non-blocking try-acquire: 포화 즉시 False → router 가 503 + Retry-After (포화 ≠ 실패,
  대기·재시도는 DRO 의 시간예산 backoff 몫 — B-1).

cap 의 SoT 는 engine.config 데이터 — 본 모듈은 키(persona id)를 열거하지 않는 범용 풀.
"""

from __future__ import annotations

import asyncio
from typing import Any

from . import engine_config


class _Pool:
    """카운터형 동시성 풀 (asyncio.Lock 보호, non-blocking try-acquire)."""

    def __init__(self, cap: int) -> None:
        self.cap = int(cap)
        self.inflight = 0
        self._lock = asyncio.Lock()

    async def try_acquire(self) -> bool:
        async with self._lock:
            if self.inflight >= self.cap:
                return False
            self.inflight += 1
            return True

    def release(self) -> None:
        # 음수 가드 — release 중복 호출은 무해 (fail-loud 대신 관측 보존)
        if self.inflight > 0:
            self.inflight -= 1


_persona_pools: dict[int, _Pool] = {}
_tool_pool: _Pool | None = None


def _persona_pool(pid: int) -> _Pool:
    pool = _persona_pools.get(pid)
    if pool is None:
        cap = int(engine_config.persona(pid)["max_concurrency"])  # 미등재 = RuntimeError
        pool = _persona_pools.setdefault(pid, _Pool(cap))
    return pool


def _get_tool_pool() -> _Pool:
    global _tool_pool
    if _tool_pool is None:
        _tool_pool = _Pool(int(engine_config.tools()["max_concurrency"]))
    return _tool_pool


async def try_acquire_persona(pid: int) -> bool:
    """persona dispatch 슬롯 — 포화 즉시 False. 미등재 persona = RuntimeError (fail-loud)."""
    return await _persona_pool(pid).try_acquire()


def release_persona(pid: int) -> None:
    pool = _persona_pools.get(pid)
    if pool is not None:
        pool.release()


async def try_acquire_tool() -> bool:
    """POST /tool 슬롯 — dispatch 와 별도 풀."""
    return await _get_tool_pool().try_acquire()


def release_tool() -> None:
    if _tool_pool is not None:
        _tool_pool.release()


def snapshot() -> dict[str, Any]:
    """관측용 — /health 노출 (cap/inflight)."""
    return {
        "personas": {
            pid: {"cap": p.cap, "inflight": p.inflight} for pid, p in sorted(_persona_pools.items())
        },
        "tool": (
            {"cap": _tool_pool.cap, "inflight": _tool_pool.inflight}
            if _tool_pool is not None
            else None
        ),
    }


def reset() -> None:
    """테스트용 — 풀 전부 폐기 (다음 acquire 시 engine.config 재읽기)."""
    global _tool_pool
    _persona_pools.clear()
    _tool_pool = None
