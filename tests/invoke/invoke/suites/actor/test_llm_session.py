"""300.Actor llm/session — AgentSession Protocol + run_stage_structured (invoke 단위).

대상: 300.Actor/src/llm/session.py
  - AgentSession (runtime_checkable Protocol) — isinstance 동작 (구현/미구현).
  - run_stage_structured: (1) adapter 가 자체 run_stage_structured 제공 시 그것을 호출,
    (2) 없으면 run_stage 텍스트 → JSON 파싱 (dict / list / 실패=None).

벤더 SDK 직접 호출 없음 — 더미 세션 객체로 Protocol/helper 만 검증.
async 는 asyncio.run(...) (pytest-asyncio mark 없이; 기존 suite 패턴).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "300.Actor"))

from src.llm.session import AgentSession, run_stage_structured  # noqa: E402


# ── 더미 세션 구현 ──────────────────────────────────────────────────────────────


class _TextSession:
    """run_stage 만 가진 (structured 미지원) adapter."""

    def __init__(self, reply: str) -> None:
        self._reply = reply
        self.seen: list[tuple[dict[str, Any], str]] = []

    @property
    def vendor(self) -> str:
        return "dummy"

    async def run_stage(self, stage: dict[str, Any], prompt: str) -> str:
        self.seen.append((stage, prompt))
        return self._reply

    async def export_items(self) -> list[Any]:
        return []

    async def close(self) -> None:
        return None


class _StructuredSession(_TextSession):
    """자체 run_stage_structured 를 제공하는 adapter."""

    def __init__(self, reply: str, structured: Any) -> None:
        super().__init__(reply)
        self._structured = structured
        self.schema_seen: Any = "UNSET"

    async def run_stage_structured(
        self,
        stage: dict[str, Any],
        prompt: str,
        *,
        response_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.schema_seen = response_schema
        return {"text": self._reply, "structured": self._structured}


# ── Protocol (runtime_checkable) ────────────────────────────────────────────────


def test_protocol_isinstance_true_for_conforming():
    assert isinstance(_TextSession("x"), AgentSession)


def test_protocol_isinstance_false_for_nonconforming():
    class _Bad:
        pass

    assert not isinstance(_Bad(), AgentSession)


# ── run_stage_structured — adapter 가 자체 메서드 제공 ───────────────────────────


def test_uses_native_structured_method_when_present():
    sess = _StructuredSession("raw-text", {"a": 1})
    out = asyncio.run(
        run_stage_structured(sess, {"id": "s0"}, "prompt", response_schema={"type": "object"})
    )
    assert out == {"text": "raw-text", "structured": {"a": 1}}
    # native 경로 → 기본 run_stage 는 호출되지 않음.
    assert sess.seen == []
    # response_schema 가 그대로 전달됨.
    assert sess.schema_seen == {"type": "object"}


# ── run_stage_structured — fallback (run_stage text → JSON 파싱) ─────────────────


def test_fallback_parses_object_json():
    sess = _TextSession('{"k": "v", "n": 2}')
    out = asyncio.run(run_stage_structured(sess, {"id": "s1"}, "p"))
    assert out == {"text": '{"k": "v", "n": 2}', "structured": {"k": "v", "n": 2}}
    # fallback 경로 → run_stage 가 stage+prompt 와 함께 호출됨.
    assert sess.seen == [({"id": "s1"}, "p")]


def test_fallback_parses_top_level_array_json():
    sess = _TextSession('[{"id": "r1"}, {"id": "r2"}]')
    out = asyncio.run(run_stage_structured(sess, {}, "p"))
    assert out["structured"] == [{"id": "r1"}, {"id": "r2"}]


def test_fallback_non_json_text_yields_none_structured():
    sess = _TextSession("이건 그냥 평문 응답입니다")
    out = asyncio.run(run_stage_structured(sess, {}, "p"))
    assert out == {"text": "이건 그냥 평문 응답입니다", "structured": None}


def test_fallback_scalar_json_not_treated_as_structured():
    """JSON 으로 파싱되지만 dict/list 가 아닌 scalar → structured=None."""
    sess = _TextSession("42")
    out = asyncio.run(run_stage_structured(sess, {}, "p"))
    assert out == {"text": "42", "structured": None}


def test_fallback_passes_response_schema_argument_without_native_method():
    """fallback 경로에선 response_schema 가 무시되어도 정상 동작."""
    sess = _TextSession('{"ok": true}')
    out = asyncio.run(run_stage_structured(sess, {}, "p", response_schema={"type": "object"}))
    assert out["structured"] == {"ok": True}
