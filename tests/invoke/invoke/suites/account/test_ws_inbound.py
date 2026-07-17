"""100.Nexus ws_inbound — client WS inbound parser/dispatcher (invoke 단위).

대상: 100.Nexus/src/ws_inbound.py. stack 없이 fake WebSocket(send_json 기록) +
message_flow.handle_message / get_cm_client(멱등 store) monkeypatch 로 전 분기 구동.

C5(A-4): inbound 은 message.send **1종**(strict). 클라 correlation_id 멱등키 — done=원결과
재-ack(처리 0), in_flight=ack(id=null), conflict=같은 id 다른 content. message.received 는
송신 소켓 unicast(data={correlation_id, id}). message.resend / _already_received 폐기.

분기 전수:
  handle_inbound        : invalid JSON / 비-dict frame / message.send / unknown action
  _validate_send_frame  : 잉여 top 키 / data 비-object / 잉여 data 키 / content 비-str·빈 /
                          correlation_id 결손
  _handle_message_send  : claimed(정상 처리+put+received) / claim 예외(internal) /
                          done 동일(재-ack) / done 다른 content(conflict) / in_flight(id=null) /
                          APIError relay(+선점해제) / 일반 예외 relay(+선점해제)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
if str(ROOT / "100.Nexus") not in sys.path:
    sys.path.insert(0, str(ROOT / "100.Nexus"))

import src.ws_inbound as ws_inbound  # noqa: E402
from src.errors import APIError  # noqa: E402
from venezia_contracts.models.dro_api.error import ErrorCode  # noqa: E402


# ── fakes ────────────────────────────────────────────────────────────────────
class FakeWS:
    """send_json 만 구현 — 발사된 envelope 들을 기록."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)


class FakeCM:
    """멱등 store fake — claim/put/delete_idempotency. claim 결과를 주입."""

    def __init__(
        self,
        *,
        claim: tuple[str, dict[str, Any] | None] = ("claimed", None),
        raises: bool = False,
        put_raises: bool = False,
    ) -> None:
        self._claim = claim
        self._raises = raises
        self._put_raises = put_raises
        self.puts: list[tuple[str, dict[str, Any]]] = []
        self.deletes: list[str] = []

    async def claim_idempotency(
        self, user_id: str, key: str, content_hash: str | None = None
    ) -> tuple[str, dict[str, Any] | None]:
        if self._raises:
            raise RuntimeError("cm down")
        self.claim_hashes = getattr(self, "claim_hashes", [])
        self.claim_hashes.append(content_hash)
        return self._claim

    async def put_idempotency(self, user_id: str, key: str, record: dict[str, Any]) -> None:
        if self._put_raises:
            raise RuntimeError("cm down on put")
        self.puts.append((key, record))

    async def delete_idempotency(self, user_id: str, key: str) -> None:
        self.deletes.append(key)


def _patch_handle_message(
    monkeypatch,
    *,
    raises: Exception | None = None,
    spawn_raises: Exception | None = None,
    message_id: int = 7,
) -> list[dict[str, Any]]:
    """write_user_turn + spawn_root_chains 패치. 반환 = write_user_turn 호출 기록(list, =처리 여부),
    `.spawns` 에 spawn_root_chains 호출 기록(재-spawn 검증용).

    raises → write_user_turn 실패(turn 미저장). spawn_raises → spawn_root_chains 실패(turn 저장 후).
    """

    class _Calls(list):  # list + .spawns 부가 추적 (기존 `calls == []` 단언 그대로 동작)
        spawns: list[dict[str, Any]]

    calls = _Calls()
    calls.spawns = []

    async def fake_write(**kwargs: Any) -> int:
        calls.append(kwargs)
        if raises is not None:
            raise raises
        return message_id

    async def fake_spawn(**kwargs: Any) -> None:
        calls.spawns.append(kwargs)
        if spawn_raises is not None:
            raise spawn_raises

    monkeypatch.setattr(ws_inbound.message_flow, "write_user_turn", fake_write)
    monkeypatch.setattr(ws_inbound.message_flow, "spawn_root_chains", fake_spawn)
    return calls


def _patch_cm(
    monkeypatch,
    *,
    claim: tuple[str, dict[str, Any] | None] = ("claimed", None),
    raises: bool = False,
    put_raises: bool = False,
) -> FakeCM:
    cm = FakeCM(claim=claim, raises=raises, put_raises=put_raises)
    monkeypatch.setattr(ws_inbound, "get_cm_client", lambda: cm)
    return cm


def _last(ws: FakeWS) -> dict[str, Any]:
    return ws.sent[-1]


def _send(ws: FakeWS, raw: str, user: str = "u", work: str = "i") -> None:
    asyncio.run(ws_inbound.handle_inbound(ws, raw, user, work))


def _frame(content: str = "hi", correlation_id: str = "c-1") -> str:
    import json

    return json.dumps(
        {"action": "message.send", "data": {"content": content, "correlation_id": correlation_id}}
    )


# ── handle_inbound dispatch ──────────────────────────────────────────────────
def test_handle_inbound_invalid_json():
    ws = FakeWS()
    _send(ws, "{not json")
    env = _last(ws)
    assert env["type"] == "system.error"
    assert set(env) == {"type", "timestamp", "seq", "data"}  # scope/subject_id 없음
    assert env["data"]["code"] == "validation_failed"
    assert "invalid JSON" in env["data"]["message"]


def test_handle_inbound_non_dict_frame():
    ws = FakeWS()
    _send(ws, "[1, 2, 3]")
    env = _last(ws)
    assert env["type"] == "system.error"
    assert env["data"]["message"] == "frame must be an object"


def test_handle_inbound_unknown_action():
    ws = FakeWS()
    _send(ws, '{"action": "message.resend"}')  # resend 폐기 — 이제 미지 action
    env = _last(ws)
    assert env["type"] == "system.error"
    assert env["data"]["code"] == "validation_failed"
    assert "unknown action" in env["data"]["message"]


# ── message.send — 정상(claimed) + received unicast ──────────────────────────
def test_message_send_valid(monkeypatch):
    calls = _patch_handle_message(monkeypatch, message_id=7)
    cm = _patch_cm(monkeypatch)
    ws = FakeWS()
    _send(ws, _frame("hi", "c-1"))
    assert len(calls) == 1
    assert calls[0] == {"user_id": "u", "work_id": "i", "content": "hi", "correlation_id": "c-1"}
    # 선점 확정(put) + received(송신 소켓 unicast, data={correlation_id, id}).
    assert cm.puts and cm.puts[0][0] == "message:i:c-1"
    assert cm.puts[0][1]["body"]["message_id"] == 7
    env = _last(ws)
    assert env["type"] == "message.received"
    assert set(env) == {"type", "timestamp", "seq", "data"}
    assert env["data"] == {"correlation_id": "c-1", "id": 7}
    # 신규 처리 → correlation_id 로 root chain spawn (결정적 chain_id)
    assert calls.spawns and calls.spawns[0]["correlation_id"] == "c-1"


def test_message_send_strips_content(monkeypatch):
    calls = _patch_handle_message(monkeypatch)
    _patch_cm(monkeypatch)
    ws = FakeWS()
    _send(ws, _frame("  hi  ", "c-2"))
    assert calls[0]["content"] == "hi"


# ── 멱등 — done(원결과 재-ack) / conflict / in_flight ─────────────────────────
def test_message_send_idempotent_replay(monkeypatch):
    # 같은 correlation_id 재send (done) → 재처리·재-spawn 0, 원 message_id 재-ack.
    # done = put 이 spawn 성공 후라 이미 처리됨 → 재-spawn 안 함(DRO coalesce 시 중복 chain 위험 방지).
    calls = _patch_handle_message(monkeypatch)
    rec = {"content_hash": ws_inbound._content_hash("hi"), "body": {"message_id": 3}}
    _patch_cm(monkeypatch, claim=("done", rec))
    ws = FakeWS()
    _send(ws, _frame("hi", "c-dup"))
    assert calls == [] and calls.spawns == []  # 새 turn·재-spawn 모두 없음
    assert _last(ws)["data"] == {"correlation_id": "c-dup", "id": 3}


def test_message_send_conflict_different_content(monkeypatch):
    # 같은 correlation_id, 다른 content → conflict.
    calls = _patch_handle_message(monkeypatch)
    rec = {"content_hash": ws_inbound._content_hash("original"), "body": {"message_id": 3}}
    _patch_cm(monkeypatch, claim=("done", rec))
    ws = FakeWS()
    _send(ws, _frame("changed", "c-dup"))
    assert calls == []
    env = _last(ws)
    assert env["type"] == "system.error"
    assert env["data"]["code"] == "conflict"


def test_message_send_in_flight_reprocesses(monkeypatch):
    # in_flight(동시 처리 중 또는 직전 크래시) — content_hash 일치 → claimed 와 동일하게 멱등 재처리
    # (write CM dedup → turn 중복 0, spawn 결정적 chain_id → DRO I1 중복 0). stale in-flight 도 완결.
    calls = _patch_handle_message(monkeypatch, message_id=7)
    cm = _patch_cm(
        monkeypatch, claim=("in_flight", {"content_hash": ws_inbound._content_hash("hi")})
    )
    ws = FakeWS()
    _send(ws, _frame("hi", "c-conc"))
    assert len(calls) == 1  # 재처리(CM 멱등이라 turn 중복 0)
    assert len(calls.spawns) == 1 and calls.spawns[0]["correlation_id"] == "c-conc"
    assert cm.puts and cm.puts[0][1]["body"]["message_id"] == 7
    assert _last(ws)["data"] == {"correlation_id": "c-conc", "id": 7}


def test_message_send_in_flight_conflict(monkeypatch):
    # 처리 중인데 같은 id·다른 content → conflict (선점 마커 hash 불일치).
    calls = _patch_handle_message(monkeypatch)
    rec = {"content_hash": ws_inbound._content_hash("original")}
    _patch_cm(monkeypatch, claim=("in_flight", rec))
    ws = FakeWS()
    _send(ws, _frame("changed", "c-conc"))
    assert calls == []
    assert _last(ws)["type"] == "system.error"
    assert _last(ws)["data"]["code"] == "conflict"


def test_message_send_claim_raises_internal(monkeypatch):
    _patch_handle_message(monkeypatch)
    _patch_cm(monkeypatch, raises=True)
    ws = FakeWS()
    _send(ws, _frame("hi", "c-x"))
    env = _last(ws)
    assert env["type"] == "system.error"
    assert env["data"]["code"] == "internal"


def test_message_send_put_failure_still_acks(monkeypatch):
    # 멱등 확정(put) 실패 — turn 은 저장됐으니 ack 유지(크래시·error 없음). W5 잔재는 내부 처리.
    calls = _patch_handle_message(monkeypatch, message_id=4)
    _patch_cm(monkeypatch, put_raises=True)
    ws = FakeWS()
    _send(ws, _frame("hi", "c-put"))
    assert len(calls) == 1  # 처리는 됨
    env = _last(ws)
    assert env["type"] == "message.received"
    assert env["data"] == {"correlation_id": "c-put", "id": 4}


# ── strict 검증 위반 → validation_failed, handle_message 미호출 ───────────────
def test_message_send_extra_top_field(monkeypatch):
    calls = _patch_handle_message(monkeypatch)
    _patch_cm(monkeypatch)
    ws = FakeWS()
    _send(
        ws,
        '{"action": "message.send", "client_msg_id": "c1", "data": {"content": "hi", "correlation_id": "c-1"}}',
    )
    assert calls == []
    assert _last(ws)["data"]["code"] == "validation_failed"
    assert "unexpected fields" in _last(ws)["data"]["message"]


def test_message_send_data_not_object(monkeypatch):
    _patch_handle_message(monkeypatch)
    _patch_cm(monkeypatch)
    ws = FakeWS()
    _send(ws, '{"action": "message.send", "data": "nope"}')
    assert _last(ws)["data"]["message"].endswith("data must be an object")


def test_message_send_extra_data_field(monkeypatch):
    _patch_handle_message(monkeypatch)
    _patch_cm(monkeypatch)
    ws = FakeWS()
    _send(
        ws,
        '{"action": "message.send", "data": {"content": "hi", "correlation_id": "c", "kind": "free"}}',
    )
    assert "unexpected data fields" in _last(ws)["data"]["message"]


def test_message_send_content_not_string(monkeypatch):
    _patch_handle_message(monkeypatch)
    _patch_cm(monkeypatch)
    ws = FakeWS()
    _send(ws, '{"action": "message.send", "data": {"content": 123, "correlation_id": "c"}}')
    assert "content (non-empty string) required" in _last(ws)["data"]["message"]


def test_message_send_empty_content(monkeypatch):
    _patch_handle_message(monkeypatch)
    _patch_cm(monkeypatch)
    ws = FakeWS()
    _send(ws, '{"action": "message.send", "data": {"content": "   ", "correlation_id": "c"}}')
    assert "content (non-empty string) required" in _last(ws)["data"]["message"]


def test_message_send_missing_correlation_id(monkeypatch):
    _patch_handle_message(monkeypatch)
    _patch_cm(monkeypatch)
    ws = FakeWS()
    _send(ws, '{"action": "message.send", "data": {"content": "hi"}}')
    env = _last(ws)
    assert env["data"]["code"] == "validation_failed"
    assert "correlation_id (string) required" in env["data"]["message"]


# ── work-guard / 처리 실패 → system.error relay + 선점 해제, received 미발사 ──
def test_message_send_work_not_found_relays_api_error(monkeypatch):
    _patch_handle_message(
        monkeypatch, raises=APIError(ErrorCode.work_not_found, 404, "work 'i' not found")
    )
    cm = _patch_cm(monkeypatch)
    ws = FakeWS()
    _send(ws, _frame("hi", "c-err"))
    env = _last(ws)
    assert env["type"] == "system.error"
    assert env["data"]["code"] == "work_not_found"
    assert cm.deletes == ["message:i:c-err"]  # 선점 해제 → 재시도 가능
    assert not any(e["type"] == "message.received" for e in ws.sent)


def test_message_send_write_failure_releases_claim(monkeypatch):
    # write_user_turn(=guard+append) 실패 = turn 미저장 → 선점 해제 안전(재시도 가능). received 없음.
    _patch_handle_message(monkeypatch, raises=RuntimeError("cm down"))
    cm = _patch_cm(monkeypatch)
    ws = FakeWS()
    _send(ws, _frame("hi", "c-err2"))
    env = _last(ws)
    assert env["type"] == "system.error"
    assert env["data"]["code"] == "internal"
    assert cm.deletes == ["message:i:c-err2"]  # 저장 0 → 해제
    assert not any(e["type"] == "message.received" for e in ws.sent)


def test_message_send_spawn_failure_releases_claim(monkeypatch):
    # spawn 실패 → done 확정 안 함(put 미도달) + **선점 해제** → 재시도가 멱등 재처리해 완결
    # (turn 은 CM correlation_id 멱등이라 중복 0, 결정적 chain_id 로 DRO I1 중복 차단). received 없음.
    calls = _patch_handle_message(monkeypatch, spawn_raises=RuntimeError("dro down"))
    cm = _patch_cm(monkeypatch)
    ws = FakeWS()
    _send(ws, _frame("hi", "c-spawn"))
    env = _last(ws)
    assert env["type"] == "system.error"
    assert env["data"]["code"] == "internal"
    assert len(calls.spawns) == 1  # spawn 시도됨
    assert cm.deletes == ["message:i:c-spawn"]  # 선점 해제 → 재시도 재처리
    assert cm.puts == []  # done 확정 안 됨 (spawn 성공 후에만 put)
    assert not any(e["type"] == "message.received" for e in ws.sent)
