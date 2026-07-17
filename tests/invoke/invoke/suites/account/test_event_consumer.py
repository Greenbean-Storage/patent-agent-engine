"""100.Nexus event_consumer — ref-counted SSE→WS fan-out 생명주기 (invoke 단위).

대상: 100.Nexus/src/event_consumer.py.

전수 분기:
  acquire
    첫 호출                 : 키별 _run task 1개 생성 + refcount=1   (38-47)
    같은 키 두 번째 호출    : task 재사용(1개) + refcount=2          (40-41, 47)
  release
    unknown key             : no-op early return                    (51-55)
    refcount>0 으로 감소     : task 유지                             (56)
    refcount 0 도달          : task.cancel + 세션 제거               (57-59)
  _run
    queue.get → handle_raw_event 호출 (drain)                       (62-68)
    handle_raw_event 예외 → log.exception 으로 swallow              (69-70)
    finally → producer cancel + suppress(CancelledError)           (71-74)
  _produce
    consume_events async-for → queue push                          (78-86)
    consume_events 예외 1회 → log.warning 후 sleep 재연결           (89-91)
  모듈 wrapper acquire/release → _manager 위임                      (98, 102)

monkeypatch: src.dro_client.consume_events / src.event_mapper.handle_raw_event.
async 테스트는 suite 패턴대로 asyncio.run(...) 직접 호출.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "100.Nexus"))

import src.dro_client as dro_client  # noqa: E402
import src.event_consumer as event_consumer  # noqa: E402
import src.event_mapper as event_mapper  # noqa: E402
from src.event_consumer import _ConsumerManager  # noqa: E402


# ── 헬퍼: consume_events fake async generator ────────────────────────────────


def _make_consume(events: list[Any], *, then_hang: bool = True, raise_once: bool = False):
    """raw event 들을 yield 한 뒤 (기본) 영원히 hang. raise_once=True 면 첫 호출 예외."""
    calls = {"n": 0}

    async def _gen(user_id: str, work_id: str):
        calls["n"] += 1
        if raise_once and calls["n"] == 1:
            raise RuntimeError("sse boom")
        for ev in events:
            yield ev
        if then_hang:
            while True:
                await asyncio.sleep(3600)

    _gen.calls = calls  # type: ignore[attr-defined]
    return _gen


def _patch(monkeypatch, consume, handler):
    monkeypatch.setattr(dro_client, "consume_events", consume)
    monkeypatch.setattr(event_mapper, "handle_raw_event", handler)


# ── acquire: 첫 호출 task 1개 + refcount, 둘째 호출 공유 ──────────────────────


def test_acquire_starts_one_task_and_refcounts(monkeypatch):
    seen: list[Any] = []

    async def _handler(raw):
        seen.append(raw)

    consume = _make_consume([{"type": "rt_started"}, {"type": "rt_progress"}])
    _patch(monkeypatch, consume, _handler)

    async def _run():
        mgr = _ConsumerManager()
        await mgr.acquire("u", "i")
        await mgr.acquire("u", "i")  # 같은 키 두 번째 — task 재사용
        key = ("u", "i")
        sess = mgr._sessions[key]
        assert sess.refcount == 2
        task = sess.task
        assert len(mgr._sessions) == 1
        await asyncio.sleep(0.05)  # _run 이 큐 drain 하도록
        # cleanup
        await mgr.release("u", "i")
        await mgr.release("u", "i")
        return task

    task = asyncio.run(_run())
    assert task.cancelled() or task.done()
    # 두 raw event 가 handle_raw_event 로 전달됨
    assert {"type": "rt_started"} in seen
    assert {"type": "rt_progress"} in seen
    # consume_events 는 키당 1번만 시작 (task 1개 공유)
    assert consume.calls["n"] == 1


# ── release: refcount 감소 / 0 도달 시 cancel+제거 / unknown no-op ────────────


def test_release_decrements_then_cancels_at_zero(monkeypatch):
    async def _handler(raw):
        return None

    _patch(monkeypatch, _make_consume([]), _handler)

    async def _run():
        mgr = _ConsumerManager()
        await mgr.acquire("u", "i")
        await mgr.acquire("u", "i")
        await mgr.release("u", "i")  # refcount 2→1, 유지
        assert mgr._sessions[("u", "i")].refcount == 1
        task = mgr._sessions[("u", "i")].task
        await mgr.release("u", "i")  # refcount 1→0, cancel + 제거
        assert ("u", "i") not in mgr._sessions
        await asyncio.sleep(0.01)
        return task

    task = asyncio.run(_run())
    assert task.cancelled() or task.done()


def test_release_unknown_key_noop(monkeypatch):
    async def _handler(raw):
        return None

    _patch(monkeypatch, _make_consume([]), _handler)

    async def _run():
        mgr = _ConsumerManager()
        # 아무 것도 acquire 안 한 상태 — early return (no error)
        await mgr.release("ghost", "x")
        assert mgr._sessions == {}

    asyncio.run(_run())


# ── _run: handle_raw_event 예외 swallow (map_failed) ─────────────────────────


def test_run_swallows_handle_raw_event_exception(monkeypatch):
    seen: list[Any] = []

    async def _handler(raw):
        seen.append(raw)
        raise ValueError("map kaboom")

    consume = _make_consume([{"type": "rt_error"}])
    _patch(monkeypatch, consume, _handler)

    async def _run():
        mgr = _ConsumerManager()
        await mgr.acquire("u", "i")
        await asyncio.sleep(0.05)  # 예외가 swallow 되고 task 가 살아있어야 함
        task = mgr._sessions[("u", "i")].task
        assert not task.done()  # 예외로 죽지 않음
        await mgr.release("u", "i")
        await asyncio.sleep(0.01)
        return task

    task = asyncio.run(_run())
    assert seen == [{"type": "rt_error"}]
    assert task.cancelled() or task.done()


# ── _produce: consume_events 예외 1회 → log.warning 후 재연결 루프 ────────────


def test_produce_reconnects_after_sse_error(monkeypatch):
    seen: list[Any] = []

    async def _handler(raw):
        seen.append(raw)

    # 첫 호출 예외 → sleep(_RECONNECT_DELAY_S) 후 둘째 호출에서 event yield
    consume = _make_consume([{"type": "rt_result"}], raise_once=True)
    _patch(monkeypatch, consume, _handler)
    # 재연결 delay 를 줄여 테스트 빠르게
    monkeypatch.setattr(event_consumer, "_RECONNECT_DELAY_S", 0.02)

    async def _run():
        mgr = _ConsumerManager()
        await mgr.acquire("u", "i")
        await asyncio.sleep(0.12)  # 예외 → 재연결 → event drain 까지
        await mgr.release("u", "i")
        await asyncio.sleep(0.01)

    asyncio.run(_run())
    # 첫 시도 예외, 둘째 시도에서 event 전달
    assert consume.calls["n"] >= 2
    assert {"type": "rt_result"} in seen


# ── _produce: 큐 가득 → overflow=oldest drop (83-86) ─────────────────────────


def test_produce_queue_overflow_drops_oldest(monkeypatch):
    # handle_raw_event 를 영원히 block 시켜 _run 이 큐를 비우지 못하게 함 → 큐가 가득 참.
    consumer_started = asyncio.Event()
    drop_done = asyncio.Event()

    async def _handler(raw):
        consumer_started.set()
        await drop_done.wait()  # 첫 event 받은 뒤 영원히 hold → 큐 drain 정지

    # maxsize=1: 첫 event 는 _run 이 꺼내가서 handler 에서 block,
    # 이후 producer 가 put_nowait → QueueFull → get_nowait(oldest drop) + put_nowait.
    monkeypatch.setattr(event_consumer, "_QUEUE_MAXSIZE", 1)

    async def _gen(user_id, work_id):
        for i in range(20):
            yield {"type": "rt_progress", "i": i}
            await asyncio.sleep(0)  # producer 가 _run 보다 앞서가도록 양보
        while True:
            await asyncio.sleep(3600)

    _patch(monkeypatch, _gen, _handler)

    captured: dict[str, int] = {}

    async def _run():
        mgr = _ConsumerManager()
        await mgr.acquire("u", "i")
        await asyncio.sleep(0.05)  # overflow drop 경로가 돌도록
        captured["drops"] = mgr._sessions[("u", "i")].queue_drops  # release(=pop) 전 캡처
        drop_done.set()  # handler 풀어서 정리 가능하게
        await asyncio.sleep(0.01)
        await mgr.release("u", "i")
        await asyncio.sleep(0.01)

    asyncio.run(_run())
    assert consumer_started.is_set()
    assert captured["drops"] > 0  # overflow oldest-drop 계측 (C3)


# ── 모듈 wrapper acquire/release → _manager 위임 ──────────────────────────────


def test_module_wrappers_delegate_to_manager(monkeypatch):
    calls: list[tuple[str, str, str]] = []

    class _FakeMgr:
        async def acquire(self, user_id, work_id):
            calls.append(("acquire", user_id, work_id))

        async def release(self, user_id, work_id):
            calls.append(("release", user_id, work_id))

    monkeypatch.setattr(event_consumer, "_manager", _FakeMgr())

    async def _run():
        await event_consumer.acquire("uu", "ii")
        await event_consumer.release("uu", "ii")

    asyncio.run(_run())
    assert calls == [("acquire", "uu", "ii"), ("release", "uu", "ii")]
