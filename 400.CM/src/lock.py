"""파일 단위 asyncio.Lock — DRO·Actor 의 동시 PATCH 직렬화."""

from __future__ import annotations

import asyncio
from collections import defaultdict


class FileLockManager:
    """resource key 별로 asyncio.Lock 1개. 같은 파일은 직렬, 다른 파일은 병행."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def lock(self, key: str) -> asyncio.Lock:
        return self._locks[key]


_manager = FileLockManager()


def lock_for(key: str) -> asyncio.Lock:
    return _manager.lock(key)
