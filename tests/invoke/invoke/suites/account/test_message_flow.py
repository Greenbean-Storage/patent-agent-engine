"""100.Nexus message_flow — 사용자 메시지 인입 흐름 invoke 단위테스트 (≥99% line).

대상: 100.Nexus/src/message_flow.py:handle_message.
- CM 은 `src.message_flow.get_cm_client` monkeypatch 로 _FakeCM 대체
  (append_conversation / patch_context_manifest 기록).
- DRO 는 `src.message_flow.dro_client.control_spawn` 를 AsyncMock 으로 대체
  (chain_id 반환 + 호출 인자 capture).

async 테스트는 기존 suite 패턴대로 동기 def 안에서 asyncio.run(...) 로 호출.

미디어는 메시지와 무관 (work 레벨 presigned S3 직접) — handle_message 는 미디어를 다루지 않음.

반환 = user turn 메시지 id(= conversation 내 0-based 위치, A-4). chain_id 는 내부 발급(미반환).

분기 전수:
  (a) FULL  : content only → user turn append + manifest patch
              + control_spawn 2회(P01+P02), 반환 message_id
  (b) SMALLTALK : P01 만 → control_spawn 1회
  (c) ENGINE_MODE case-insensitive ('full' → FULL)
  (d) user_turn_meta : user turn 에 meta
  chain_id : control_spawn 가 Nexus 내부 발급 chain_id 로 호출됨 (spawn args 에서 capture)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "100.Nexus"))

from src import message_flow as mf  # noqa: E402
from src.config import P01_ENTRY, P02_ENTRY  # noqa: E402

_UID = "u-1"
_INV = "i-1"


# ── fakes ──────────────────────────────────────────────────────────────────


class _FakeCM:
    """handle_message 가 호출하는 CM 메서드만 구현 + 호출 기록."""

    def __init__(self, work_exists: bool = True) -> None:
        self.conversation: list[dict[str, Any]] = []
        self.manifest_patches: list[list[dict[str, Any]]] = []
        # work-guard: None 이면 work 미존재(404). 기본은 존재.
        self._manifest: dict[str, Any] | None = {"title": "x"} if work_exists else None

    async def get_context_manifest(self, user_id, work_id):
        return self._manifest

    async def append_conversation(self, user_id, work_id, turn):
        assert user_id == _UID and work_id == _INV
        # prod CM 미러 — meta.correlation_id 멱등 append (같은 corr 면 기존 위치 반환, 중복 0)
        corr = (turn.get("meta") or {}).get("correlation_id")
        if corr is not None:
            for i, t in enumerate(self.conversation):
                if (t.get("meta") or {}).get("correlation_id") == corr:
                    return i
        self.conversation.append(turn)
        return len(self.conversation) - 1  # 메시지 id = 0-based 위치

    async def patch_context_manifest(self, user_id, work_id, ops):
        self.manifest_patches.append(ops)
        return {"ok": True}


def _patch(monkeypatch, *, engine_mode: str = "FULL", work_exists: bool = True):
    """공통 환경 구성 — FakeCM + control_spawn AsyncMock + ENGINE_MODE 주입."""
    cm = _FakeCM(work_exists=work_exists)
    monkeypatch.setattr(mf, "get_cm_client", lambda: cm)
    monkeypatch.setattr(mf.settings, "ENGINE_MODE", engine_mode)

    spawn = AsyncMock(side_effect=lambda *a, **k: a[4])  # arg4 = chain_id 반향
    monkeypatch.setattr(mf.dro_client, "control_spawn", spawn)
    return cm, spawn


# ── (a) FULL — content only ──────────────────────────────────────────────────


def test_full_content_only(monkeypatch):
    cm, spawn = _patch(monkeypatch, engine_mode="FULL")

    result = asyncio.run(mf.handle_message(_UID, _INV, "hello"))

    # 반환 = user turn 메시지 id(= 0-based 위치)
    assert result == 0

    # user turn append
    assert len(cm.conversation) == 1
    turn = cm.conversation[0]
    assert turn["role"] == "user"
    assert turn["content"] == "hello"
    assert "timestamp" in turn
    assert "meta" not in turn

    # manifest last_activity patch
    assert len(cm.manifest_patches) == 1
    ops = cm.manifest_patches[0]
    assert ops[0]["op"] == "add"
    assert ops[0]["path"] == "/last_activity_at"

    # control_spawn 2회 (P01 + P02) — chain_id 는 내부 발급(spawn args 에서 capture)
    assert spawn.await_count == 2
    p01_pid, p01_persona = P01_ENTRY
    p02_pid, p02_persona = P02_ENTRY
    trig = {"kind": "user_message"}
    first, second = spawn.await_args_list
    p01_chain, p02_chain = first.args[4], second.args[4]
    assert first.args == (_UID, _INV, p01_persona, p01_pid, p01_chain, trig)
    assert second.args == (_UID, _INV, p02_persona, p02_pid, p02_chain, trig)
    assert p01_chain != p02_chain  # 서로 다른 Nexus 발급 chain_id


# ── (b) SMALLTALK — P01 만 ───────────────────────────────────────────────────


def test_smalltalk_only_p01(monkeypatch):
    cm, spawn = _patch(monkeypatch, engine_mode="SMALLTALK")

    result = asyncio.run(mf.handle_message(_UID, _INV, "yo"))

    assert result == 0
    assert spawn.await_count == 1
    p01_pid, p01_persona = P01_ENTRY
    only = spawn.await_args_list[0]
    assert only.args == (_UID, _INV, p01_persona, p01_pid, only.args[4], {"kind": "user_message"})

    # conversation + manifest 는 그대로
    assert len(cm.conversation) == 1
    assert len(cm.manifest_patches) == 1


def test_engine_mode_case_insensitive(monkeypatch):
    """ENGINE_MODE='full' (소문자) 도 .upper() 로 FULL 처리 → P02 spawn."""
    _, spawn = _patch(monkeypatch, engine_mode="full")
    result = asyncio.run(mf.handle_message(_UID, _INV, "hi"))
    assert result == 0
    assert spawn.await_count == 2


# ── (c) user_turn_meta ───────────────────────────────────────────────────────


def test_user_turn_meta(monkeypatch):
    cm, _ = _patch(monkeypatch, engine_mode="FULL")
    meta = {"kind": "roadmap.answer", "roadmap_item_id": "r-7"}
    asyncio.run(mf.handle_message(_UID, _INV, "answer", user_turn_meta=meta))
    assert cm.conversation[0]["meta"] == meta


# ── (d) work-guard — 없는 work 면 APIError(work_not_found), 부수효과 없음 ─────────


def test_work_not_found_raises_and_no_side_effects(monkeypatch):
    import pytest
    from src.errors import APIError
    from venezia_contracts.models.dro_api.error import ErrorCode

    cm, spawn = _patch(monkeypatch, engine_mode="FULL", work_exists=False)
    with pytest.raises(APIError) as ei:
        asyncio.run(mf.handle_message(_UID, _INV, "hello"))
    assert ei.value.code == ErrorCode.work_not_found
    assert ei.value.status == 404
    # append/patch/spawn 전혀 안 일어남 (guard 가 가장 먼저)
    assert cm.conversation == []
    assert cm.manifest_patches == []
    assert spawn.await_count == 0


# ── (e) 결정적 chain_id — 재-spawn 멱등(DRO I1)의 근거 (A-4 / W5 해소) ─────────


def test_chain_id_for_deterministic():
    # correlation_id 있으면 결정적(uuid5) — 같은 입력=같은 id (재-spawn 시 I1 멱등 → 중복 실행 0).
    a = mf._chain_id_for("w1", "corr-1", 1)
    assert a == mf._chain_id_for("w1", "corr-1", 1)
    # work/persona/correlation 다르면 다른 id
    assert mf._chain_id_for("w1", "corr-1", 2) != a
    assert mf._chain_id_for("w2", "corr-1", 1) != a
    assert mf._chain_id_for("w1", "corr-2", 1) != a
    # correlation_id 없으면(REST roadmap) 랜덤 — 매번 다름
    assert mf._chain_id_for("w1", None, 1) != mf._chain_id_for("w1", None, 1)


def test_spawn_root_chains_correlation_deterministic(monkeypatch):
    # spawn_root_chains 에 correlation_id 주면 control_spawn 이 결정적 chain_id 로 호출 — 재-spawn 안전.
    _, spawn = _patch(monkeypatch, engine_mode="FULL")
    asyncio.run(mf.spawn_root_chains(_UID, _INV, correlation_id="c-1"))
    ids1 = [c.args[4] for c in spawn.await_args_list]
    spawn.reset_mock()
    asyncio.run(mf.spawn_root_chains(_UID, _INV, correlation_id="c-1"))
    ids2 = [c.args[4] for c in spawn.await_args_list]
    assert ids1 == ids2 and len(ids1) == 2 and ids1[0] != ids1[1]  # 같은 corr=같은 id, P01≠P02


def test_write_user_turn_correlation_idempotent(monkeypatch):
    # 같은 correlation_id 로 두 번 write → turn 1개(중복 0) + 같은 메시지 id (CM 멱등 append).
    cm, _ = _patch(monkeypatch, engine_mode="FULL")
    id1 = asyncio.run(mf.write_user_turn(_UID, _INV, "hi", correlation_id="c-1"))
    id2 = asyncio.run(mf.write_user_turn(_UID, _INV, "hi", correlation_id="c-1"))
    assert id1 == id2
    assert len(cm.conversation) == 1  # 재처리해도 turn 중복 없음
    assert cm.conversation[0]["meta"]["correlation_id"] == "c-1"
    # 다른 correlation_id → 새 turn
    id3 = asyncio.run(mf.write_user_turn(_UID, _INV, "yo", correlation_id="c-2"))
    assert id3 == 1 and len(cm.conversation) == 2
