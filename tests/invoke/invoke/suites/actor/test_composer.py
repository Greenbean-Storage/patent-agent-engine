"""src.composer (300.Actor) — compose_prompt 전 분기 + helper (순수+async)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "300.Actor"))

from src import composer as C  # noqa: E402


async def _cm(rel: str):
    return {"resource": rel, "n": 1}


def _run(coro):
    return asyncio.run(coro)


def _roots(tmp_path: Path) -> tuple[Path, Path]:
    kroot = tmp_path / "knowledge"
    (kroot).mkdir()
    (kroot / "guide.md").write_text("KNOWLEDGE BODY", encoding="utf-8")
    proot = tmp_path / "pipelines"
    (proot / "P01.R00").mkdir(parents=True)
    (proot / "P01.R00" / "task.md").write_text("DO THE TASK", encoding="utf-8")
    return kroot, proot


def test_compose_full(tmp_path):
    kroot, proot = _roots(tmp_path)
    out = _run(
        C.compose_prompt(
            persona_prompt="PERSONA TEXT",
            inject_context={"kb": "@knowledge/guide.md", "iom": "cm://invention_object_model"},
            recommended_context={"more": "@knowledge/x.md"},
            fragments={"frag1": "FRAG BODY"},
            instructions={"reference": "@pipelines/P01.R00/task.md"},
            dispatch_choice_guide={0: "exit", 1: "continue"},
            knowledge_root=kroot,
            pipelines_root=proot,
            cm_fetch=_cm,
        )
    )
    assert "[PERSONA]" in out and "PERSONA TEXT" in out
    assert "[CONTEXT]" in out and "KNOWLEDGE BODY" in out
    assert '"resource"' in out  # cm:// fetch dict → _stringify json
    assert "[FRAGMENTS]" in out and "FRAG BODY" in out
    assert "[TASK]" in out and "DO THE TASK" in out
    assert "[DISPATCH_CHOICE_GUIDE]" in out and "1: continue" in out
    assert "[RECOMMENDED_FETCH]" in out and "more" in out


def test_compose_empty():
    out = _run(
        C.compose_prompt(
            persona_prompt="",
            inject_context={},
            recommended_context={},
            fragments={},
            instructions=None,
            dispatch_choice_guide=None,
            knowledge_root=Path("/x"),
            pipelines_root=Path("/x"),
            cm_fetch=None,
        )
    )
    assert out == ""


def test_compose_instructions_inline():
    out = _run(
        C.compose_prompt(
            persona_prompt="",
            inject_context={},
            recommended_context={},
            fragments={},
            instructions={"inline": "INLINE TASK"},
            dispatch_choice_guide=None,
            knowledge_root=Path("/x"),
            pipelines_root=Path("/x"),
            cm_fetch=None,
        )
    )
    assert "[TASK]\nINLINE TASK" in out


def _compose(**kw):
    base = dict(
        persona_prompt="",
        inject_context={},
        recommended_context={},
        fragments={},
        instructions=None,
        dispatch_choice_guide=None,
        knowledge_root=Path("/x"),
        pipelines_root=Path("/x"),
        cm_fetch=None,
    )
    base.update(kw)
    return _run(C.compose_prompt(**base))


def test_inject_knowledge_missing_file_inline_error(tmp_path):
    kroot = tmp_path / "k"
    kroot.mkdir()
    out = _compose(inject_context={"x": "@knowledge/nope.md"}, knowledge_root=kroot)
    assert "fetch 실패" in out


def test_inject_cm_without_fetch_inline_error():
    out = _compose(inject_context={"x": "cm://iom"}, cm_fetch=None)
    assert "fetch 실패" in out


def test_inject_unknown_prefix_inline_error():
    out = _compose(inject_context={"x": "bad://y"})
    assert "fetch 실패" in out


def test_instructions_errors():
    with pytest.raises(C.ComposerError):
        _compose(instructions={"inline": 123})  # non-str
    with pytest.raises(C.ComposerError):
        _compose(instructions={"reference": 123})  # non-str
    with pytest.raises(C.ComposerError):
        _compose(instructions=["legacy"])  # non-dict
    with pytest.raises(C.ComposerError):
        _compose(instructions={"inline": "a", "reference": "b"})  # 2 keys
    with pytest.raises(C.ComposerError):
        _compose(instructions={"bogus": "x"})  # extra key
    assert _compose(instructions={}) == ""  # empty → None → no TASK


def test_instructions_reference_unknown_prefix():
    with pytest.raises(C.ComposerError):
        _compose(instructions={"reference": "cm://not-pipelines"})


def test_instructions_inline_multiline_no_bullet_join():
    out = _compose(instructions={"inline": "**1. 첫 번째**\n**2. 두 번째**"})
    assert "[TASK]" in out and "**2. 두 번째**" in out
    assert "\n- **1." not in out  # bullet join 폐기 회귀


def test_instructions_reference_missing_file(tmp_path):
    C._read_instructions_file.cache_clear()
    with pytest.raises(C.ComposerError):
        _compose(
            instructions={"reference": "@pipelines/missing.md"},
            pipelines_root=tmp_path,
        )


def test_stringify():
    assert C._stringify("text") == "text"
    assert '"a"' in C._stringify({"a": 1})
