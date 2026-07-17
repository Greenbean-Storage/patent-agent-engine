"""300.Actor llm/__init__ — create_session (persona, mode 분기) 전수 (invoke 단위).

대상: 300.Actor/src/llm/__init__.py:create_session
  - persona 설정 SoT = engine.config (미등재 persona → RuntimeError fail-loud).
  - 잘못된 LLM_MODE → RuntimeError (fail-loud).
  - FIXTURE: step_id+pipeline_id 필수 (없으면 RuntimeError), 있으면 FixtureSession 반환
    (persona/sdk/model/pipeline_id/step_id/fixture_dir/history 정합).
  - PRODUCTION: engine.config 운영값(fallback/effort/retry/defaults)을 주입한
    ActorSession 직접 생성.

settings.LLM_MODE 는 monkeypatch.setattr 로 직접 교체 (env reload 불필요).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "300.Actor"))

import src.llm as llm_mod  # noqa: E402
from src.llm import create_session  # noqa: E402
from src.llm.fixture import FixtureSession  # noqa: E402


def _set_mode(monkeypatch, mode) -> None:
    monkeypatch.setattr(llm_mod.settings, "LLM_MODE", mode)


# ── persona 검증 ────────────────────────────────────────────────────────────────


def test_unknown_persona_fails_loud(monkeypatch):
    """미등재 persona — 수락 집합의 SoT = engine.config personas 키."""
    _set_mode(monkeypatch, "FIXTURE")
    with pytest.raises(RuntimeError, match="수락 집합"):
        create_session(99, step_id="s0", pipeline_id="P01.R00.X")


# ── MODE fail-loud ──────────────────────────────────────────────────────────────


def test_invalid_mode_raises_runtime_error(monkeypatch):
    _set_mode(monkeypatch, "ECHO_LLM")
    with pytest.raises(RuntimeError, match="Invalid LLM_MODE"):
        create_session(1, step_id="s0", pipeline_id="P01.R00.X")


def test_empty_mode_raises_runtime_error(monkeypatch):
    """settings.LLM_MODE 가 빈 문자열 → '' upper → 허용 set 미포함 → fail-loud."""
    _set_mode(monkeypatch, "")
    with pytest.raises(RuntimeError, match="Invalid LLM_MODE"):
        create_session(1, step_id="s0", pipeline_id="P01.R00.X")


def test_mode_is_case_insensitive(monkeypatch):
    """소문자 'fixture' → upper() → FIXTURE 로 정규화되어 정상 동작."""
    _set_mode(monkeypatch, "fixture")
    sess = create_session(1, step_id="s0", pipeline_id="P01.R00.X")
    assert isinstance(sess, FixtureSession)


# ── FIXTURE 경로 ────────────────────────────────────────────────────────────────


def test_fixture_requires_step_and_pipeline(monkeypatch):
    _set_mode(monkeypatch, "FIXTURE")
    with pytest.raises(RuntimeError, match="step_id"):
        create_session(1)


def test_fixture_missing_pipeline_id_raises(monkeypatch):
    _set_mode(monkeypatch, "FIXTURE")
    with pytest.raises(RuntimeError, match="step_id"):
        create_session(1, step_id="s0")


def test_fixture_missing_step_id_raises(monkeypatch):
    _set_mode(monkeypatch, "FIXTURE")
    with pytest.raises(RuntimeError, match="step_id"):
        create_session(1, pipeline_id="P01.R00.X")


def test_fixture_returns_fixture_session_with_fields(monkeypatch):
    _set_mode(monkeypatch, "FIXTURE")
    monkeypatch.setattr(llm_mod.settings, "FIXTURE_PATH", "/tmp/fx")
    prior = {
        "schema_version": 1,
        "vendor": "fixture",
        "model": "m",
        "items": [{"role": "user", "content": "hi"}],
    }
    sess = create_session(
        2, prior_state=prior, step_id="s3", pipeline_id="P02.R00.CONCEPT_MATURITY"
    )
    assert isinstance(sess, FixtureSession)
    assert sess.persona == 2
    # persona 2 → claude/claude-opus-4-7 (engine.config personas."2").
    assert sess.sdk == "claude"
    assert sess.model == "claude-opus-4-7"
    assert sess.pipeline_id == "P02.R00.CONCEPT_MATURITY"
    assert sess.step_id == "s3"
    assert sess.fixture_dir == "/tmp/fx"
    # prior envelope (vendor=fixture) → history 복원 — 복사본.
    assert sess.history == prior["items"]
    assert sess.history is not prior["items"]


def test_fixture_none_prior_defaults_empty(monkeypatch):
    _set_mode(monkeypatch, "FIXTURE")
    sess = create_session(1, step_id="s0", pipeline_id="P01.R00.X")
    assert sess.history == []


# ── PRODUCTION 위임 ─────────────────────────────────────────────────────────────


def test_production_builds_actor_session_from_engine_config(monkeypatch):
    """PRODUCTION — engine.config 운영값이 ActorSession 에 전부 주입되는지."""
    _set_mode(monkeypatch, "PRODUCTION")
    from src.actor_session import ActorSession

    prior = {
        "schema_version": 1,
        "vendor": "openai",
        "model": "o3",
        "items": [{"role": "assistant", "content": "x"}],
    }
    out = create_session(4, prior_state=prior)
    assert isinstance(out, ActorSession)
    # persona 4 = engine.config personas."4" (openai/o3, effort medium)
    assert out.persona == 4
    assert out.sdk == "openai"
    assert out.model == "o3"
    assert out.fallback_model == "o3"
    assert out.effort == "medium"
    assert out.llm_settings == {}
    assert out.retry_cfg == {"max_attempts": 3, "backoff_seconds": [2, 5, 10]}
    assert out.defaults_cfg["max_iterations"] == 10
    assert out.prior_state == prior
