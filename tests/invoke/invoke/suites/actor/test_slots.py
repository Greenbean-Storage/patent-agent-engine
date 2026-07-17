"""src.slots (300.Actor) — persona/tool 동시성 풀 전 분기.

cap 의 SoT = engine.config (ENGINE_CONFIG_FILE — invoke cli 가 주입).
구 1-slot busy 폐기 (Actor 재설계 A2·D-3): persona 별 cap + tool 풀 분리.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "300.Actor"))

from src import engine_config, slots  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setenv("ENGINE_CONFIG_FILE", str(ROOT / "@deployment" / "engine.config.yaml"))
    engine_config._load.cache_clear()
    slots.reset()
    yield
    slots.reset()
    engine_config._load.cache_clear()


def _run(coro):
    return asyncio.run(coro)


def test_persona_cap_enforced_from_engine_config():
    """persona 2 cap=2 (engine.config) — cap 까지 True, 초과 즉시 False."""
    cap = int(engine_config.persona(2)["max_concurrency"])

    async def _go():
        grants = [await slots.try_acquire_persona(2) for _ in range(cap + 1)]
        return grants

    grants = _run(_go())
    assert grants == [True] * cap + [False]


def test_release_frees_slot_and_negative_guard():
    async def _go():
        assert await slots.try_acquire_persona(2)
        slots.release_persona(2)
        # 음수 가드 — 중복 release 무해
        slots.release_persona(2)
        slots.release_persona(2)
        return await slots.try_acquire_persona(2)

    assert _run(_go()) is True
    assert slots.snapshot()["personas"][2]["inflight"] == 1


def test_persona_pools_independent():
    async def _go():
        assert await slots.try_acquire_persona(1)
        assert await slots.try_acquire_persona(2)
        return slots.snapshot()

    snap = _run(_go())
    assert snap["personas"][1]["inflight"] == 1
    assert snap["personas"][2]["inflight"] == 1


def test_tool_pool_separate_from_persona():
    """tool 풀은 dispatch(persona) 와 비공유 — 구 1-slot 공유 폐기."""
    tool_cap = int(engine_config.tools()["max_concurrency"])

    async def _go():
        # persona 슬롯 점유가 tool 풀에 영향 없음
        assert await slots.try_acquire_persona(2)
        grants = [await slots.try_acquire_tool() for _ in range(tool_cap + 1)]
        return grants

    grants = _run(_go())
    assert grants == [True] * tool_cap + [False]
    slots.release_tool()
    assert slots.snapshot()["tool"]["inflight"] == tool_cap - 1


def test_release_tool_before_init_is_noop():
    slots.release_tool()  # 풀 미생성 상태 — 무해
    assert slots.snapshot()["tool"] is None


def test_release_persona_unknown_pid_is_noop():
    slots.release_persona(42)  # 풀 미생성 — 무해
    assert slots.snapshot()["personas"] == {}


def test_unknown_persona_fails_loud():
    with pytest.raises(RuntimeError, match="수락 집합"):
        _run(slots.try_acquire_persona(99))


def test_reset_drops_pools():
    async def _go():
        await slots.try_acquire_persona(1)
        await slots.try_acquire_tool()

    _run(_go())
    slots.reset()
    snap = slots.snapshot()
    assert snap["personas"] == {}
    assert snap["tool"] is None
