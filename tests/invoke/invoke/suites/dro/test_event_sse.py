"""200.DRO event_sse — per-session raw event SSE producer.

전략: stack 없이 _RawEventHub / 모듈 레벨 emit_raw·subscribe 를 직접 구동.
- emit_raw: 키별 monotonic seq, envelope 필드 전부, step 옵션, 구독자 없을 때 best-effort,
  여러 구독자 fan-out, QueueFull oldest-drop.
- subscribe: 큐 등록 → SSE 프레임 yield → aclose 시 구독 해제 (subscribers pop).

async 는 asyncio.run(...) 로 (pytest-asyncio mark 없이; 기존 suite 패턴).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "200.DRO"))

from src import event_sse as E  # noqa: E402
from src.event_sse import _RawEventHub, emit_raw, subscribe  # noqa: E402


def _parse_frame(frame: str) -> tuple[str, dict]:
    """sse.event 포맷 'event: <name>\\ndata: <json>\\n\\n' 파싱."""
    lines = frame.split("\n")
    assert lines[0].startswith("event: ")
    assert lines[1].startswith("data: ")
    name = lines[0][len("event: ") :]
    data = json.loads(lines[1][len("data: ") :])
    return name, data


def test_emit_raw_no_subscriber_best_effort():
    """구독자 없으면 push 대상 0개 — 에러 없이 seq 만 증가."""

    async def run():
        hub = _RawEventHub()
        await hub.emit_raw("u1", "i1", "rt_started", {"rt": "a"})
        await hub.emit_raw("u1", "i1", "rt_result", {"rt": "a"})
        # seq 는 키별로 monotonic 증가
        assert hub._seq[("u1", "i1")] == 2
        # 구독자 등록 없었으므로 subscribers 비어있음
        assert hub.subscribers == {}

    asyncio.run(run())


def test_emit_raw_envelope_and_seq_and_step():
    """envelope 전 필드 + 키별 독립 monotonic seq + step 객체."""

    async def run():
        hub = _RawEventHub()
        q: asyncio.Queue = asyncio.Queue()
        hub.subscribers[("u1", "i1")] = [q]

        await hub.emit_raw(
            "u1",
            "i1",
            "rt_progress",
            {"phase": "llm"},
            persona=3,
            step={"id": "s0", "display_status": "thinking", "extra": "dropped"},
        )
        evt = q.get_nowait()
        assert evt["type"] == "rt_progress"
        assert evt["user_id"] == "u1"
        assert evt["work_id"] == "i1"
        assert evt["persona"] == 3
        assert evt["seq"] == 1
        assert evt["payload"] == {"phase": "llm"}
        assert isinstance(evt["timestamp"], str)
        # step 은 id/display_status 만 발췌 (extra 제외)
        assert evt["step"] == {"id": "s0", "display_status": "thinking"}

        # 두 번째 emit — 같은 키 seq=2, persona None / step 없음
        await hub.emit_raw("u1", "i1", "rt_result", {"ok": True})
        evt2 = q.get_nowait()
        assert evt2["seq"] == 2
        assert evt2["persona"] is None
        assert "step" not in evt2

        # 다른 키는 독립 seq (1 부터)
        q2: asyncio.Queue = asyncio.Queue()
        hub.subscribers[("u2", "i2")] = [q2]
        await hub.emit_raw("u2", "i2", "rt_started", {})
        assert q2.get_nowait()["seq"] == 1

    asyncio.run(run())


def test_emit_raw_step_missing_keys_default_none():
    """step dict 에 id/display_status 가 없으면 None 으로 채움."""

    async def run():
        hub = _RawEventHub()
        q: asyncio.Queue = asyncio.Queue()
        hub.subscribers[("u", "i")] = [q]
        await hub.emit_raw("u", "i", "rt_progress", {}, step={})
        evt = q.get_nowait()
        assert evt["step"] == {"id": None, "display_status": None}

    asyncio.run(run())


def test_emit_raw_fan_out_multiple_subscribers():
    """같은 키 구독자 여러 개 — 모두 push."""

    async def run():
        hub = _RawEventHub()
        q1: asyncio.Queue = asyncio.Queue()
        q2: asyncio.Queue = asyncio.Queue()
        hub.subscribers[("u", "i")] = [q1, q2]
        await hub.emit_raw("u", "i", "rt_started", {"n": 1})
        assert q1.get_nowait()["payload"] == {"n": 1}
        assert q2.get_nowait()["payload"] == {"n": 1}

    asyncio.run(run())


def test_emit_raw_queue_full_oldest_drop():
    """큐가 가득 차면 oldest drop 후 재시도 — 에러 없이 새 이벤트 보존."""

    async def run():
        hub = _RawEventHub()
        q: asyncio.Queue = asyncio.Queue(maxsize=2)
        hub.subscribers[("u", "i")] = [q]
        # maxsize 2 까지 채움
        await hub.emit_raw("u", "i", "e", {"i": 0})
        await hub.emit_raw("u", "i", "e", {"i": 1})
        assert q.full()
        # 3번째 — QueueFull → oldest(i=0) drop → i=2 put. 에러 없음.
        await hub.emit_raw("u", "i", "e", {"i": 2})
        first = q.get_nowait()
        second = q.get_nowait()
        # oldest(seq 1) 가 빠지고 seq 2,3 이 남음
        assert [first["payload"]["i"], second["payload"]["i"]] == [1, 2]

    asyncio.run(run())


def test_subscribe_yields_frames_then_deregisters():
    """subscribe 제너레이터: 등록 → SSE 프레임 yield → aclose 시 구독 해제."""

    async def run():
        hub = _RawEventHub()
        gen = hub.subscribe("u1", "i1")
        # 첫 anext 가 큐 등록을 수행 — task 로 돌려 등록을 기다림
        first_task = asyncio.create_task(gen.__anext__())
        # 등록될 때까지 양보
        for _ in range(100):
            await asyncio.sleep(0)
            if hub.subscribers.get(("u1", "i1")):
                break
        assert len(hub.subscribers[("u1", "i1")]) == 1

        await hub.emit_raw("u1", "i1", "rt_started", {"x": 1}, persona=1)
        frame1 = await first_task
        name1, data1 = _parse_frame(frame1)
        assert name1 == "rt_started"
        assert data1["payload"] == {"x": 1}
        assert data1["seq"] == 1

        # 두 번째 이벤트도 yield
        await hub.emit_raw("u1", "i1", "rt_result", {"x": 2})
        frame2 = await gen.__anext__()
        name2, data2 = _parse_frame(frame2)
        assert name2 == "rt_result"
        assert data2["seq"] == 2

        # 종료 → finally 가 구독 해제 + 키 비면 pop
        await gen.aclose()
        assert ("u1", "i1") not in hub.subscribers

    asyncio.run(run())


def test_subscribe_deregister_keeps_key_when_other_subscriber():
    """구독자 2명 중 1명 close — 키는 남고 그 큐만 제거."""

    async def run():
        hub = _RawEventHub()
        # 잔류 구독자 1명을 미리 등록
        survivor: asyncio.Queue = asyncio.Queue()
        hub.subscribers[("u", "i")] = [survivor]

        gen = hub.subscribe("u", "i")
        task = asyncio.create_task(gen.__anext__())
        for _ in range(100):
            await asyncio.sleep(0)
            if len(hub.subscribers.get(("u", "i"), [])) == 2:
                break
        assert len(hub.subscribers[("u", "i")]) == 2

        await hub.emit_raw("u", "i", "e", {})
        await task  # 한 프레임 받아 generator 진행
        await gen.aclose()

        # 키는 남고 survivor 만 유지
        assert hub.subscribers[("u", "i")] == [survivor]

    asyncio.run(run())


def test_module_level_emit_and_subscribe_delegate_to_hub():
    """모듈 레벨 emit_raw / subscribe 가 싱글턴 _hub 로 위임."""

    async def run():
        gen = subscribe("mu", "mi")
        task = asyncio.create_task(gen.__anext__())
        for _ in range(100):
            await asyncio.sleep(0)
            if E._hub.subscribers.get(("mu", "mi")):
                break
        assert E._hub.subscribers.get(("mu", "mi"))

        await emit_raw("mu", "mi", "rt_started", {"y": 9}, persona=2)
        frame = await task
        name, data = _parse_frame(frame)
        assert name == "rt_started"
        assert data["payload"] == {"y": 9}
        assert data["persona"] == 2

        await gen.aclose()
        assert ("mu", "mi") not in E._hub.subscribers

    asyncio.run(run())
