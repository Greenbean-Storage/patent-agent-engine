"""300.Actor llm/fixture — FixtureSession 전수 (invoke 단위).

대상: 300.Actor/src/llm/fixture.py
  - FixtureSession.run: {fixture_dir}/{pipeline_id}/{step_id}.json 을 replay.
    structured(dict/list) hit / 파일 없음(miss → echo) / dict 도 list 도 아님(None → echo) /
    JSON decode error(except 분기 → None → echo) 를 진짜 assert.
  - _fixture_path / _load / history append / export_state·prior_state (컨텍스트 ② envelope).

임시 fixture 파일은 tmp_path 로 생성 (fixture_dir 인자로 직접 주입).
async 는 asyncio.run(...) (pytest-asyncio mark 없이; 기존 suite 패턴).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "300.Actor"))

from src.llm.fixture import FixtureSession  # noqa: E402


def _session(
    fixture_dir: Path, pipeline_id: str = "P01.R00.X", step_id: str = "s0"
) -> FixtureSession:
    return FixtureSession(
        persona=1,
        sdk="gemini",
        model="gemini-3.1-pro-preview",
        pipeline_id=pipeline_id,
        step_id=step_id,
        fixture_dir=str(fixture_dir),
    )


def _write_fixture(fixture_dir: Path, pipeline_id: str, step_id: str, content: str) -> Path:
    p = fixture_dir / pipeline_id / f"{step_id}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# ── _fixture_path ─────────────────────────────────────────────────────────────


def test_fixture_path_layout(tmp_path):
    s = _session(tmp_path, "P02.R00.CONCEPT_MATURITY", "step-3")
    expected = tmp_path / "P02.R00.CONCEPT_MATURITY" / "step-3.json"
    assert s._fixture_path() == expected


# ── _load ───────────────────────────────────────────────────────────────────────


def test_load_dict(tmp_path):
    _write_fixture(tmp_path, "P01.R00.X", "s0", json.dumps({"a": 1}))
    s = _session(tmp_path)
    assert s._load() == {"a": 1}


def test_load_list(tmp_path):
    """top-level JSON array root (예: update_roadmap output) 도 허용."""
    _write_fixture(tmp_path, "P01.R00.X", "s0", json.dumps([{"id": "r1"}, {"id": "r2"}]))
    s = _session(tmp_path)
    assert s._load() == [{"id": "r1"}, {"id": "r2"}]


def test_load_file_not_found_returns_none(tmp_path):
    s = _session(tmp_path, "P09.NONE.X", "missing")
    assert s._load() is None


def test_load_not_dict_or_list_returns_none(tmp_path):
    """JSON 이 scalar (string) → isinstance(data, dict|list) False → warning + None."""
    _write_fixture(tmp_path, "P01.R00.X", "s0", json.dumps("just a string"))
    s = _session(tmp_path)
    assert s._load() is None


def test_load_invalid_json_returns_none(tmp_path):
    """JSON decode error → 일반 except 분기 → warning + None."""
    _write_fixture(tmp_path, "P01.R00.X", "s0", "{not valid json,,,")
    s = _session(tmp_path)
    assert s._load() is None


# ── run: hit (structured dict) ────────────────────────────────────────────────


def test_run_structured_dict_hit(tmp_path):
    _write_fixture(tmp_path, "P01.R00.X", "s0", json.dumps({"decision": "go", "score": 0.9}))
    s = _session(tmp_path)
    out = asyncio.run(s.run("user says hi"))
    assert out["structured"] == {"decision": "go", "score": 0.9}
    assert out["text"] == "(fixture P01.R00.X/s0)"
    # history: user turn + assistant turn (structured JSON dumped)
    assert s.history[0] == {"role": "user", "content": "user says hi"}
    assert s.history[1]["role"] == "assistant"
    assert json.loads(s.history[1]["content"]) == {"decision": "go", "score": 0.9}


def test_run_structured_list_hit(tmp_path):
    _write_fixture(tmp_path, "P01.R00.X", "s0", json.dumps([{"id": "r1"}]))
    s = _session(tmp_path)
    out = asyncio.run(s.run("roadmap please"))
    assert out["structured"] == [{"id": "r1"}]
    assert out["text"] == "(fixture P01.R00.X/s0)"
    assert json.loads(s.history[1]["content"]) == [{"id": "r1"}]


def test_run_non_ascii_preserved_in_history(tmp_path):
    """history dump 는 ensure_ascii=False — 한글이 escape 되지 않음."""
    _write_fixture(tmp_path, "P01.R00.X", "s0", json.dumps({"한글": "값"}, ensure_ascii=False))
    s = _session(tmp_path)
    asyncio.run(s.run("안녕"))
    assert "한글" in s.history[1]["content"]
    assert "값" in s.history[1]["content"]


# ── run: miss (echo fallback) ─────────────────────────────────────────────────


def test_run_miss_echo_fallback(tmp_path):
    s = _session(tmp_path, "P03.R00.PRIOR_ART", "search")
    out = asyncio.run(s.run("find prior art"))
    assert out["structured"] is None
    assert out["text"] == ("[FIXTURE-MISS persona=1 pipeline=P03.R00.PRIOR_ART step=search]")
    # history still records both turns; assistant content == echo text
    assert s.history[0] == {"role": "user", "content": "find prior art"}
    assert s.history[1] == {"role": "assistant", "content": out["text"]}


def test_run_scalar_fixture_also_echoes(tmp_path):
    """파일은 있지만 scalar JSON → _load None → echo miss 경로."""
    _write_fixture(tmp_path, "P01.R00.X", "s0", json.dumps(42))
    s = _session(tmp_path)
    out = asyncio.run(s.run("hi"))
    assert out["structured"] is None
    assert out["text"].startswith("[FIXTURE-MISS persona=1")


def test_run_ignores_extra_kwargs(tmp_path):
    """run 의 선택 인자 (system_prompt/tools/...) 는 무시되고 동작에 영향 없음."""
    _write_fixture(tmp_path, "P01.R00.X", "s0", json.dumps({"ok": True}))
    s = _session(tmp_path)
    out = asyncio.run(
        s.run(
            "prompt",
            system_prompt="sys",
            tools=[{"name": "fetch_dialog"}],
            media_refs=["cm://x"],
            max_iterations=3,
            response_schema={"type": "object"},
            context={"k": "v"},
            function_tools=[object()],
        )
    )
    assert out["structured"] == {"ok": True}


# ── export_state / prior_state (컨텍스트 ②) ──────────────────────────────────────


def test_export_state_envelope_is_copy(tmp_path):
    _write_fixture(tmp_path, "P01.R00.X", "s0", json.dumps({"ok": 1}))
    s = _session(tmp_path)
    asyncio.run(s.run("hi"))
    env = s.export_state()
    assert env["schema_version"] == 1
    assert env["vendor"] == "fixture"
    assert env["model"] == s.model
    assert env["items"] == s.history
    # items 는 복사본 — export 변조가 내부 history 에 닿지 않음
    env["items"].append({"role": "user", "content": "mutated"})
    assert len(s.history) == 2


def test_export_state_empty_before_run(tmp_path):
    s = _session(tmp_path)
    assert s.export_state()["items"] == []


def test_prior_state_fixture_vendor_restores_history(tmp_path):
    prior = {
        "schema_version": 1,
        "vendor": "fixture",
        "model": "m",
        "items": [{"role": "user", "content": "earlier"}],
    }
    s = _session(tmp_path)
    s2 = type(s)(
        persona=s.persona,
        sdk=s.sdk,
        model=s.model,
        pipeline_id=s.pipeline_id,
        step_id=s.step_id,
        fixture_dir=s.fixture_dir,
        prior_state=prior,
    )
    assert s2.history == [{"role": "user", "content": "earlier"}]
    assert s2.history is not prior["items"]


def test_prior_state_other_vendor_downgrades_to_plain(tmp_path):
    """vendor 불일치 (예: openai 원형) → items_to_plain 강등으로 history 구성."""
    prior = {
        "schema_version": 1,
        "vendor": "openai",
        "model": "o3",
        "items": [
            {"role": "user", "content": "질문"},
            {"type": "reasoning", "id": "rs_1"},
            {"role": "assistant", "content": [{"type": "output_text", "text": "답변"}]},
        ],
    }
    s = _session(tmp_path)
    s2 = type(s)(
        persona=s.persona,
        sdk=s.sdk,
        model=s.model,
        pipeline_id=s.pipeline_id,
        step_id=s.step_id,
        fixture_dir=s.fixture_dir,
        prior_state=prior,
    )
    assert s2.history == [
        {"role": "user", "content": "질문"},
        {"role": "assistant", "content": "답변"},
    ]
