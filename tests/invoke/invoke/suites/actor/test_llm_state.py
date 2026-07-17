"""300.Actor llm/state — agent_state envelope build/parse + vendor 변환 (invoke 단위).

대상: 300.Actor/src/llm/state.py (컨텍스트 ② — A3·D-2)
  - build_agent_state / parse_agent_state (legacy fail-loud · default 동형 · vendor 검증)
  - items_to_plain 3사 + fixture (텍스트 강등 추출)
  - claude_session_id (sessionId 추출 + UUID 검증 fail-loud)
  - ClaudeTranscriptStore (uuid upsert append / load None / subpath 분리)
  - openai_seed_items (same-model id strip / cross-model reasoning drop)
  - plain_to_gemini_events / plain_to_preamble

SDK import 0 — plain dict 만. async 는 asyncio.run (기존 suite 패턴).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "300.Actor"))

from src.llm import state  # noqa: E402

SID = "11111111-2222-3333-4444-555555555555"


# ── build / parse ─────────────────────────────────────────────────────────────


def test_build_agent_state_shape():
    env = state.build_agent_state("gemini", "gemini-3.1-pro-preview", [{"a": 1}])
    assert env == {
        "schema_version": 1,
        "vendor": "gemini",
        "model": "gemini-3.1-pro-preview",
        "items": [{"a": 1}],
    }


def test_build_agent_state_unknown_vendor_raises():
    with pytest.raises(RuntimeError, match="unknown agent_state vendor"):
        state.build_agent_state("mystery", "m", [])


def test_parse_agent_state_default_envelope_is_no_prior():
    # CM default (미존재 시) — items 빈 envelope 동형 → prior 없음
    cm_default = {
        "persona": 2,
        "schema_version": 1,
        "vendor": None,
        "model": None,
        "items": [],
        "updated_at": "t",
    }
    assert state.parse_agent_state(cm_default) is None


def test_parse_agent_state_roundtrip():
    env = state.build_agent_state("claude", "claude-opus-4-7", [{"sessionId": SID}])
    stored = {**env, "persona": 2, "updated_at": "t"}  # CM 스탬프 포함 형태
    parsed = state.parse_agent_state(stored)
    assert parsed is not None
    assert parsed["vendor"] == "claude"
    assert parsed["model"] == "claude-opus-4-7"
    assert parsed["items"] == [{"sessionId": SID}]


def test_parse_agent_state_items_with_unknown_vendor_raises():
    with pytest.raises(RuntimeError, match="vendor 불명"):
        state.parse_agent_state({"items": [{"x": 1}], "vendor": "wat"})


def test_parse_agent_state_legacy_messages_fail_loud():
    legacy = {"persona": 1, "messages": [{"role": "user", "content": "hi"}], "updated_at": "t"}
    with pytest.raises(RuntimeError, match="legacy agent_state"):
        state.parse_agent_state(legacy)


def test_parse_agent_state_old_empty_default_is_no_prior():
    # 구 CM default ({"messages": []}) — 비어 있으면 legacy 아님, prior 없음으로 통과
    assert state.parse_agent_state({"persona": 1, "messages": [], "updated_at": "t"}) is None


def test_parse_agent_state_non_dict_raises():
    with pytest.raises(RuntimeError, match="dict 가 아님"):
        state.parse_agent_state(["nope"])  # type: ignore[arg-type]


# ── items_to_plain ────────────────────────────────────────────────────────────


def test_items_to_plain_claude_entries():
    items = [
        {"type": "summary", "summary": "t"},  # 비 turn — 스킵
        {
            "type": "user",
            "uuid": "u1",
            "sessionId": SID,
            "message": {"role": "user", "content": "질문"},
        },
        {
            "type": "assistant",
            "uuid": "a1",
            "sessionId": SID,
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "내부 사고"},  # text 키 없음 — 강등 제외
                    {"type": "text", "text": "답변"},
                ],
            },
        },
        {"type": "user", "isMeta": True, "message": {"role": "user", "content": "meta"}},
        {"type": "user", "isSidechain": True, "message": {"role": "user", "content": "sub"}},
    ]
    assert state.items_to_plain("claude", items) == [
        {"role": "user", "content": "질문"},
        {"role": "assistant", "content": "답변"},
    ]


def test_items_to_plain_gemini_events():
    items = [
        {"author": "user", "content": {"role": "user", "parts": [{"text": "질문"}]}},
        {
            "author": "actor_1",
            "content": {"role": "model", "parts": [{"text": "답"}, {"text": "변"}]},
        },
        {"author": "actor_1", "content": {"role": "model", "parts": [{"function_call": {}}]}},
    ]
    assert state.items_to_plain("gemini", items) == [
        {"role": "user", "content": "질문"},
        {"role": "assistant", "content": "답\n변"},
    ]


def test_items_to_plain_openai_items():
    items = [
        {"role": "user", "content": "질문"},
        {"type": "reasoning", "id": "rs_1", "summary": []},  # role 없음 — 스킵
        {"type": "function_call", "name": "f", "arguments": "{}"},
        {
            "role": "assistant",
            "content": [{"type": "output_text", "text": "답변"}],
        },
    ]
    assert state.items_to_plain("openai", items) == [
        {"role": "user", "content": "질문"},
        {"role": "assistant", "content": "답변"},
    ]


def test_items_to_plain_fixture_passthrough_and_unknown_vendor():
    items = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": ""}]
    assert state.items_to_plain("fixture", items) == [{"role": "user", "content": "hi"}]
    with pytest.raises(RuntimeError, match="unknown vendor"):
        state.items_to_plain("wat", items)


# ── claude_session_id ─────────────────────────────────────────────────────────


def test_claude_session_id_extracts_first_valid():
    items = [{"type": "summary"}, {"type": "user", "sessionId": SID}]
    assert state.claude_session_id(items) == SID


def test_claude_session_id_non_uuid_raises():
    with pytest.raises(RuntimeError, match="UUID 아님"):
        state.claude_session_id([{"sessionId": "not-a-uuid"}])


def test_claude_session_id_absent_raises():
    with pytest.raises(RuntimeError, match="sessionId 없음"):
        state.claude_session_id([{"type": "user"}])


# ── ClaudeTranscriptStore ─────────────────────────────────────────────────────


def _key(session_id: str = SID, subpath: str | None = None) -> dict:
    k: dict = {"project_key": "p", "session_id": session_id}
    if subpath:
        k["subpath"] = subpath
    return k


def test_store_append_upserts_by_uuid_and_appends_no_uuid():
    async def _run():
        store = state.ClaudeTranscriptStore()
        await store.append(_key(), [{"uuid": "u1", "v": 1}, {"kind": "title"}])
        # overlap 재전송 — u1 교체 (중복 없이), title 류는 그대로 append
        await store.append(_key(), [{"uuid": "u1", "v": 2}, {"uuid": "u2", "v": 1}])
        assert store.export() == [{"uuid": "u1", "v": 2}, {"kind": "title"}, {"uuid": "u2", "v": 1}]

    asyncio.run(_run())


def test_store_load_main_and_empty_none():
    async def _run():
        empty = state.ClaudeTranscriptStore()
        assert await empty.load(_key()) is None
        seeded = state.ClaudeTranscriptStore(entries=[{"uuid": "u1", "sessionId": SID}])
        loaded = await seeded.load(_key())
        assert loaded == [{"uuid": "u1", "sessionId": SID}]

    asyncio.run(_run())


def test_store_subpath_separated_and_excluded_from_export():
    async def _run():
        store = state.ClaudeTranscriptStore()
        await store.append(_key(), [{"uuid": "m1"}])
        await store.append(_key(subpath="subagents/agent-x"), [{"uuid": "s1"}])
        assert await store.load(_key(subpath="subagents/agent-x")) is None  # SDK 가 스킵
        assert store.export() == [{"uuid": "m1"}]  # subpath 는 envelope 제외

    asyncio.run(_run())


# ── openai_seed_items ─────────────────────────────────────────────────────────


def test_openai_seed_same_model_strips_reasoning_id_only():
    items = [
        {"role": "user", "content": "q"},
        {"type": "reasoning", "id": "rs_1", "summary": ["s"]},
    ]
    out = state.openai_seed_items(items, "o3", "o3")
    assert out == [{"role": "user", "content": "q"}, {"type": "reasoning", "summary": ["s"]}]
    # 원본 무변형 (저장은 무변형 원칙 — seed 가 복사본 생성)
    assert items[1]["id"] == "rs_1"


def test_openai_seed_cross_model_drops_reasoning():
    items = [
        {"role": "user", "content": "q"},
        {"type": "reasoning", "id": "rs_1", "summary": ["s"]},
        {"role": "assistant", "content": "a"},
    ]
    out = state.openai_seed_items(items, "o3", "o4-mini")
    assert out == [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]


# ── plain_to_* ────────────────────────────────────────────────────────────────


def test_plain_to_gemini_events_roles_and_author():
    plain = [
        {"role": "user", "content": "질문"},
        {"role": "assistant", "content": "답변"},
        {"role": "assistant", "content": ""},
    ]
    events = state.plain_to_gemini_events(plain, agent_author="actor_2")
    assert events == [
        {"author": "user", "content": {"role": "user", "parts": [{"text": "질문"}]}},
        {"author": "actor_2", "content": {"role": "model", "parts": [{"text": "답변"}]}},
    ]


def test_plain_to_preamble_format_and_empty():
    assert state.plain_to_preamble([]) == ""
    out = state.plain_to_preamble([{"role": "user", "content": "hello"}])
    assert out.startswith("## 이전 대화 (Continuation)")
    assert "### user\nhello" in out
