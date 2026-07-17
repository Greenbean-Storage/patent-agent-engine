"""Fetch tool 도메인 전수 (invoke 단위) — 300.Actor/src/tools/fetch/__init__.py.

make_fetch_tools 가 RT-scoped closure 로 6 tool 을 만든다:
  fetch_dialog / fetch_step_output / fetch_drawing / list_drawings /
  fetch_outputs / fetch_conversation.

각 tool 은 AsyncMock CMClient 를 통해 해당 cm.* 메서드를 호출하고
None → {} fallback 을 처리한다.
closure 가 고정한 user/invention/persona/chain 식별자가 cm 호출에 그대로 전달되는지,
None/빈 응답이 {} 로 정규화되는지 진짜 assert.

async 는 asyncio.run(...) (pytest-asyncio mark 없이; suite 패턴).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "300.Actor"))
sys.path.insert(0, str(ROOT / "shared"))

from src.tools.fetch import make_fetch_tools  # noqa: E402

_U = "user-uuid"
_INV = "inv-uuid"
_PERSONA = 3
_CHAIN = "chain-1"


def _tools(cm):
    """make_fetch_tools 의 6 tool 을 이름→callable dict 로."""
    fns = make_fetch_tools(cm, _U, _INV, _PERSONA, _CHAIN)
    return {f.__name__: f for f in fns}


def test_returns_six_tools_in_order():
    cm = AsyncMock()
    fns = make_fetch_tools(cm, _U, _INV, _PERSONA, _CHAIN)
    assert [f.__name__ for f in fns] == [
        "fetch_dialog",
        "fetch_step_output",
        "fetch_drawing",
        "list_drawings",
        "fetch_outputs",
        "fetch_conversation",
    ]


# ── fetch_dialog ────────────────────────────────────────────────────────────────


def test_fetch_dialog_passthrough():
    cm = AsyncMock()
    cm.get_persona_dialog.return_value = {"turns": [1, 2]}
    out = asyncio.run(_tools(cm)["fetch_dialog"]("research"))
    assert out == {"turns": [1, 2]}
    cm.get_persona_dialog.assert_awaited_once_with(_U, _INV, _PERSONA, "research")


def test_fetch_dialog_none_to_empty():
    cm = AsyncMock()
    cm.get_persona_dialog.return_value = None
    out = asyncio.run(_tools(cm)["fetch_dialog"]("research"))
    assert out == {}


# ── fetch_step_output ───────────────────────────────────────────────────────────


def test_fetch_step_output_passthrough():
    cm = AsyncMock()
    cm.get_step_output.return_value = {"text": "done"}
    out = asyncio.run(_tools(cm)["fetch_step_output"]("step3"))
    assert out == {"text": "done"}
    cm.get_step_output.assert_awaited_once_with(_U, _INV, _PERSONA, _CHAIN, "step3")


def test_fetch_step_output_none_to_empty():
    cm = AsyncMock()
    cm.get_step_output.return_value = None
    out = asyncio.run(_tools(cm)["fetch_step_output"]("step3"))
    assert out == {}


# ── fetch_drawing ───────────────────────────────────────────────────────────────


def test_fetch_drawing_passthrough():
    cm = AsyncMock()
    cm.get_drawing_part.return_value = {"numerals": []}
    out = asyncio.run(_tools(cm)["fetch_drawing"]("dwg1", "numerals"))
    assert out == {"numerals": []}
    cm.get_drawing_part.assert_awaited_once_with(_U, _INV, "dwg1", "numerals")


def test_fetch_drawing_none_to_empty():
    cm = AsyncMock()
    cm.get_drawing_part.return_value = None
    out = asyncio.run(_tools(cm)["fetch_drawing"]("dwg1", "dl"))
    assert out == {}


# ── list_drawings ───────────────────────────────────────────────────────────────


def test_list_drawings_passthrough():
    cm = AsyncMock()
    cm.get_drawing_manifest.return_value = {"drawings": ["d1"]}
    out = asyncio.run(_tools(cm)["list_drawings"]())
    assert out == {"drawings": ["d1"]}
    cm.get_drawing_manifest.assert_awaited_once_with(_U, _INV)


def test_list_drawings_none_to_empty():
    cm = AsyncMock()
    cm.get_drawing_manifest.return_value = None
    out = asyncio.run(_tools(cm)["list_drawings"]())
    assert out == {}


# ── fetch_outputs ───────────────────────────────────────────────────────────────


def test_fetch_outputs_passthrough():
    cm = AsyncMock()
    cm.get_outputs_list.return_value = {"outputs": ["draft.docx"]}
    out = asyncio.run(_tools(cm)["fetch_outputs"]())
    assert out == {"outputs": ["draft.docx"]}
    cm.get_outputs_list.assert_awaited_once_with(_U, _INV)


def test_fetch_outputs_none_to_empty():
    cm = AsyncMock()
    cm.get_outputs_list.return_value = None
    out = asyncio.run(_tools(cm)["fetch_outputs"]())
    assert out == {}


# ── fetch_conversation ──────────────────────────────────────────────────────────


def test_fetch_conversation_passthrough():
    cm = AsyncMock()
    cm.get_conversation.return_value = {"messages": [{"role": "user"}]}
    out = asyncio.run(_tools(cm)["fetch_conversation"]())
    assert out == {"messages": [{"role": "user"}]}
    cm.get_conversation.assert_awaited_once_with(_U, _INV)


def test_fetch_conversation_none_to_empty():
    cm = AsyncMock()
    cm.get_conversation.return_value = None
    out = asyncio.run(_tools(cm)["fetch_conversation"]())
    assert out == {}


# ── closure 식별자 격리 (다른 persona/chain 으로 새 tool) ─────────────────────────


def test_closure_captures_distinct_identifiers():
    cm = AsyncMock()
    cm.get_persona_dialog.return_value = {}
    cm.get_step_output.return_value = {}
    t = _tools(cm)
    asyncio.run(t["fetch_dialog"]("decisions"))
    asyncio.run(t["fetch_step_output"]("s0"))
    cm.get_persona_dialog.assert_awaited_once_with(_U, _INV, _PERSONA, "decisions")
    cm.get_step_output.assert_awaited_once_with(_U, _INV, _PERSONA, _CHAIN, "s0")

    cm2 = AsyncMock()
    cm2.get_persona_dialog.return_value = {}
    t2 = {f.__name__: f for f in make_fetch_tools(cm2, "u2", "i2", 5, "c2")}
    asyncio.run(t2["fetch_dialog"]("workspace"))
    cm2.get_persona_dialog.assert_awaited_once_with("u2", "i2", 5, "workspace")


# ── D-3: allowed_names 선언 제어 (step 의 llm_tools 선언이 실제 노출 제어) ──────────


def test_allowed_names_filters_to_declared():
    cm = AsyncMock()
    fns = make_fetch_tools(
        cm, _U, _INV, _PERSONA, _CHAIN, allowed_names=["fetch_dialog", "fetch_conversation"]
    )
    # all_tools 순서 보존, 선언된 2종만
    assert [f.__name__ for f in fns] == ["fetch_dialog", "fetch_conversation"]


def test_allowed_names_empty_returns_no_tools():
    cm = AsyncMock()
    fns = make_fetch_tools(cm, _U, _INV, _PERSONA, _CHAIN, allowed_names=[])
    assert fns == []  # 선언 0개 → fetch 도구 0개 (현 전 pipeline 의 기본 상태)


def test_allowed_names_none_returns_all_six():
    cm = AsyncMock()
    fns = make_fetch_tools(cm, _U, _INV, _PERSONA, _CHAIN, allowed_names=None)
    assert len(fns) == 6  # None = 전체 (하위호환)
