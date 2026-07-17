"""100.Nexus client WS registry — invoke 단위테스트 (≥99% line).

대상: 100.Nexus/src/ws_manager.py (WSRegistry + get_production_ws_registry).

  add/remove   : 등록/해제 후 connection 수 반환 (다른 ws 보존 분기 포함)
  emit_business: envelope v2 shape {type,timestamp,seq,data} (scope/subject_id 없음) ·
                 키별 monotonic seq (호출 누적) · replay buffer append ·
                 전 conn broadcast · send_json raise → dead-conn prune
  replay_since : 빈 buffer no-op · since_seq 이내 → seq>since 만 replay ·
                 buffer evict → system.resync_required · replay 중 send 실패 → return

async 테스트는 기존 suite 패턴대로 동기 def 안에서 asyncio.run(...) 로 호출.
"""

from __future__ import annotations

import asyncio
import sys
from collections import deque
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "100.Nexus"))

from src import ws_manager as wm  # noqa: E402
from src.ws_manager import (  # noqa: E402
    WSRegistry,
    get_production_ws_registry,
)

_UID = "u-1"
_INV = "inv-1"


# ── fakes ──────────────────────────────────────────────────────────────────


class _FakeWS:
    """send_json 을 기록하는 정상 WebSocket."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


class _DeadWS:
    """send_json 이 항상 raise 하는 죽은 WebSocket."""

    def __init__(self) -> None:
        self.attempts = 0

    async def send_json(self, payload: dict) -> None:
        self.attempts += 1
        raise RuntimeError("connection closed")


# ── add / remove ─────────────────────────────────────────────────────────────


def test_add_returns_count():
    reg = WSRegistry()
    ws_a = _FakeWS()
    ws_b = _FakeWS()
    n1 = asyncio.run(reg.add(_UID, _INV, ws_a))
    n2 = asyncio.run(reg.add(_UID, _INV, ws_b))
    assert n1 == 1
    assert n2 == 2
    assert len(reg.connections[(_UID, _INV)]) == 2


def test_remove_returns_remaining_count_and_keeps_others():
    reg = WSRegistry()
    ws_a = _FakeWS()
    ws_b = _FakeWS()
    asyncio.run(reg.add(_UID, _INV, ws_a))
    asyncio.run(reg.add(_UID, _INV, ws_b))
    remaining = asyncio.run(reg.remove(_UID, _INV, ws_a))
    assert remaining == 1
    survivors = [c.websocket for c in reg.connections[(_UID, _INV)]]
    assert survivors == [ws_b]


def test_remove_missing_key_returns_zero():
    reg = WSRegistry()
    ws_a = _FakeWS()
    assert asyncio.run(reg.remove("nope", "missing", ws_a)) == 0


def test_remove_last_connection_gcs_keys():
    # 마지막 연결 해제(remaining 0) → connections/replay/_seq_per_key 키 GC (C1, 메모리 bound).
    reg = WSRegistry()
    ws_a = _FakeWS()
    asyncio.run(reg.add(_UID, _INV, ws_a))
    asyncio.run(reg.emit_business(_UID, _INV, "work.progress", {"x": 1}))  # replay/_seq 생성
    key = (_UID, _INV)
    assert key in reg.replay and key in reg._seq_per_key
    assert asyncio.run(reg.remove(_UID, _INV, ws_a)) == 0
    assert key not in reg.connections
    assert key not in reg.replay
    assert key not in reg._seq_per_key


def test_remove_keeps_keys_while_other_connection_lives():
    # 다른 연결이 남으면 GC 안 함 (replay/_seq 보존).
    reg = WSRegistry()
    ws_a, ws_b = _FakeWS(), _FakeWS()
    asyncio.run(reg.add(_UID, _INV, ws_a))
    asyncio.run(reg.add(_UID, _INV, ws_b))
    asyncio.run(reg.emit_business(_UID, _INV, "work.progress", {"x": 1}))
    assert asyncio.run(reg.remove(_UID, _INV, ws_a)) == 1
    key = (_UID, _INV)
    assert [c.websocket for c in reg.connections[key]] == [ws_b]
    assert key in reg.replay and key in reg._seq_per_key


# ── emit_business ────────────────────────────────────────────────────────────


def test_emit_business_envelope_shape_and_seq_and_replay():
    reg = WSRegistry()
    ws_a = _FakeWS()
    asyncio.run(reg.add(_UID, _INV, ws_a))

    asyncio.run(reg.emit_business(_UID, _INV, "model.maturity", {"overall": 0.5}))
    assert len(ws_a.sent) == 1
    env = ws_a.sent[0]
    assert set(env) == {"type", "timestamp", "seq", "data"}
    assert env["type"] == "model.maturity"
    assert isinstance(env["timestamp"], str)
    assert env["seq"] == 1
    assert env["data"] == {"overall": 0.5}

    # 두 번째 호출 → 키별 monotonic seq 누적
    asyncio.run(reg.emit_business(_UID, _INV, "model.roadmap", {}))
    assert ws_a.sent[1]["seq"] == 2

    # replay buffer 에 두 이벤트 누적
    buf = list(reg.replay[(_UID, _INV)])
    assert [e["seq"] for e in buf] == [1, 2]


def test_emit_business_broadcasts_to_all_connections():
    reg = WSRegistry()
    ws_a = _FakeWS()
    ws_b = _FakeWS()
    asyncio.run(reg.add(_UID, _INV, ws_a))
    asyncio.run(reg.add(_UID, _INV, ws_b))
    asyncio.run(reg.emit_business(_UID, _INV, "output.ready", {}))
    assert len(ws_a.sent) == 1
    assert len(ws_b.sent) == 1


def test_emit_business_prunes_dead_connection():
    reg = WSRegistry()
    ws_live = _FakeWS()
    ws_dead = _DeadWS()
    asyncio.run(reg.add(_UID, _INV, ws_live))
    asyncio.run(reg.add(_UID, _INV, ws_dead))

    asyncio.run(reg.emit_business(_UID, _INV, "work.failed", {"message": "x"}))
    # live 는 받고, dead 는 시도 후 제거됨
    assert len(ws_live.sent) == 1
    assert ws_dead.attempts == 1
    survivors = [c.websocket for c in reg.connections[(_UID, _INV)]]
    assert survivors == [ws_live]


def test_emit_business_prune_all_dead_gcs_key():
    # 유일 연결이 죽음 → _prune_dead 가 빈 → 키 GC (C1, _gc_locked 분기).
    reg = WSRegistry()
    ws_dead = _DeadWS()
    asyncio.run(reg.add(_UID, _INV, ws_dead))
    asyncio.run(reg.emit_business(_UID, _INV, "work.progress", {"x": 1}))
    assert ws_dead.attempts == 1
    key = (_UID, _INV)
    assert key not in reg.connections
    assert key not in reg.replay
    assert key not in reg._seq_per_key


def test_emit_business_none_invention_uses_empty_key():
    reg = WSRegistry()
    asyncio.run(reg.emit_business(_UID, None, "model.roadmap", {}))
    # work_id=None → 키는 "" 로 정규화 (봉투엔 subject_id 없음)
    env = list(reg.replay[(_UID, "")])[0]
    assert set(env) == {"type", "timestamp", "seq", "data"}
    assert (_UID, "") in reg.replay


# ── replay_since ─────────────────────────────────────────────────────────────


def test_replay_since_empty_buffer_noop():
    # since_seq=0 + 빈 버퍼 = fresh → 보낼 것 없음 (resync 불요).
    reg = WSRegistry()
    ws = _FakeWS()
    asyncio.run(reg.replay_since(_UID, _INV, ws, 0))
    assert ws.sent == []


def test_replay_since_empty_buffer_reconnect_resyncs():
    # 빈 버퍼인데 since_seq>0 (재연결인데 버퍼 소실 — C1 GC/서버 재시작) → system.resync_required (C3).
    reg = WSRegistry()
    ws = _FakeWS()
    asyncio.run(reg.replay_since(_UID, _INV, ws, 5))
    assert len(ws.sent) == 1
    assert ws.sent[0]["type"] == "system.resync_required"
    assert set(ws.sent[0]) == {"type", "timestamp", "seq", "data"}
    assert "empty buffer" in ws.sent[0]["data"]["reason"]


def test_replay_since_replays_only_after_since_seq():
    reg = WSRegistry()
    asyncio.run(reg.emit_business(_UID, _INV, "a", {"i": 1}))
    asyncio.run(reg.emit_business(_UID, _INV, "b", {"i": 2}))
    asyncio.run(reg.emit_business(_UID, _INV, "c", {"i": 3}))

    ws = _FakeWS()
    asyncio.run(reg.replay_since(_UID, _INV, ws, 1))
    assert [e["seq"] for e in ws.sent] == [2, 3]


def test_replay_since_buffer_evicted_emits_resync_required():
    reg = WSRegistry()
    # maxlen 작은 buffer 로 oldest_seq 가 1 보다 크게 evict 된 상황 재현
    key = (_UID, _INV)
    reg.replay[key] = deque(
        [
            {"type": "x", "timestamp": "t", "seq": 50, "data": {}},
            {"type": "y", "timestamp": "t", "seq": 51, "data": {}},
        ],
        maxlen=200,
    )
    ws = _FakeWS()
    asyncio.run(reg.replay_since(_UID, _INV, ws, 5))
    assert len(ws.sent) == 1
    env = ws.sent[0]
    assert env["type"] == "system.resync_required"
    assert set(env) == {"type", "timestamp", "seq", "data"}
    assert env["seq"] == 0
    assert "buffer evicted" in env["data"]["reason"]


def test_replay_since_seq_reset_emits_resync_required():
    # GC 후 재연결 + 신규 emit → seq 리셋(낮은 seq). 옛 since_seq 가 newest 보다 큼 → resync (codex).
    reg = WSRegistry()
    reg.replay[(_UID, _INV)] = deque(
        [{"type": "x", "timestamp": "t", "seq": 1, "data": {}}],
        maxlen=200,
    )
    ws = _FakeWS()
    asyncio.run(reg.replay_since(_UID, _INV, ws, 100))  # 옛 세션 since_seq=100 > newest=1
    assert len(ws.sent) == 1
    assert ws.sent[0]["type"] == "system.resync_required"
    assert "seq reset" in ws.sent[0]["data"]["reason"]


def test_replay_since_resync_send_failure_swallowed():
    # evict 상황에서 resync send 가 죽은 소켓이면 조용히 통과 (예외 전파 없음).
    reg = WSRegistry()
    reg.replay[(_UID, _INV)] = deque(
        [{"type": "x", "timestamp": "t", "seq": 50, "data": {}}],
        maxlen=200,
    )
    ws = _DeadWS()
    asyncio.run(reg.replay_since(_UID, _INV, ws, 5))  # raise 없이 return
    assert ws.attempts == 1


def test_replay_since_boundary_oldest_minus_one_replays():
    # since_seq == oldest_seq - 1 → resync 아님 (경계), seq>since 만 replay
    reg = WSRegistry()
    key = (_UID, _INV)
    reg.replay[key] = deque(
        [
            {"type": "x", "timestamp": "t", "seq": 10, "data": {}},
            {"type": "y", "timestamp": "t", "seq": 11, "data": {}},
        ],
        maxlen=200,
    )
    ws = _FakeWS()
    asyncio.run(reg.replay_since(_UID, _INV, ws, 9))
    assert [e["seq"] for e in ws.sent] == [10, 11]


def test_replay_since_send_failure_mid_replay_returns():
    reg = WSRegistry()
    asyncio.run(reg.emit_business(_UID, _INV, "a", {}))
    asyncio.run(reg.emit_business(_UID, _INV, "b", {}))
    ws = _DeadWS()
    # 첫 send 에서 raise → 조용히 return (예외 전파 없음)
    asyncio.run(reg.replay_since(_UID, _INV, ws, 0))
    assert ws.attempts == 1


# ── singleton ────────────────────────────────────────────────────────────────


def test_get_production_ws_registry_singleton():
    r1 = get_production_ws_registry()
    r2 = get_production_ws_registry()
    assert r1 is r2
    assert isinstance(r1, WSRegistry)
    assert r1 is wm._production_registry
