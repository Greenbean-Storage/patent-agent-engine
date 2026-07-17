"""src.engine_config (300.Actor) — engine.config 로더 전 분기.

SoT 파일 = @deployment/engine.config.yaml (ENGINE_CONFIG_FILE env 로 지정 —
invoke cli 가 actor suite 에 주입). fail-loud 분기는 tmp 파일로 검증.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "300.Actor"))

from src import engine_config as EC  # noqa: E402

REAL = ROOT / "@deployment" / "engine.config.yaml"


@pytest.fixture(autouse=True)
def _fresh_cache():
    EC._load.cache_clear()
    yield
    EC._load.cache_clear()


def _use(monkeypatch, path: Path) -> None:
    monkeypatch.setenv("ENGINE_CONFIG_FILE", str(path))


def test_load_real_config(monkeypatch):
    _use(monkeypatch, REAL)
    data = EC._load()
    assert set(data["personas"]) == {"1", "2", "3", "4", "5", "6"}


def test_missing_file(monkeypatch, tmp_path):
    _use(monkeypatch, tmp_path / "nope.yaml")
    with pytest.raises(RuntimeError, match="not found"):
        EC._load()


def test_non_mapping(monkeypatch, tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("- just\n- a list\n", encoding="utf-8")
    _use(monkeypatch, p)
    with pytest.raises(RuntimeError, match="mapping"):
        EC._load()


def test_missing_section(monkeypatch, tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("personas: {'1': {}}\nvendors: {}\ntools: {}\n", encoding="utf-8")
    _use(monkeypatch, p)
    with pytest.raises(RuntimeError, match="필수 섹션"):
        EC._load()


def test_empty_personas(monkeypatch, tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("personas: {}\nvendors: {}\ntools: {}\ndefaults: {}\n", encoding="utf-8")
    _use(monkeypatch, p)
    with pytest.raises(RuntimeError, match="personas"):
        EC._load()


def test_persona_lookup_and_ids(monkeypatch):
    _use(monkeypatch, REAL)
    entry = EC.persona(2)
    assert entry["llm"]["sdk"] == "claude"
    assert entry["channel"] == "analysis"
    assert entry["memory_dir"] == "02.director"
    assert EC.persona_ids() == [1, 2, 3, 4, 5, 6]


def test_persona_unknown(monkeypatch):
    _use(monkeypatch, REAL)
    with pytest.raises(RuntimeError, match="수락 집합"):
        EC.persona(99)


def test_persona_llm_incomplete(monkeypatch, tmp_path):
    p = tmp_path / "cfg.yaml"
    p.write_text(
        "personas:\n"
        "  '7': {name: X, role: r, channel: c, memory_dir: 07.x,"
        " llm: {sdk: claude}, max_concurrency: 1}\n"
        "vendors: {}\ntools: {}\ndefaults: {}\n",
        encoding="utf-8",
    )
    _use(monkeypatch, p)
    with pytest.raises(RuntimeError, match="불완전"):
        EC.persona(7)


def test_vendor_retry(monkeypatch):
    _use(monkeypatch, REAL)
    r = EC.vendor_retry("claude")
    assert r["max_attempts"] == 3
    assert r["backoff_seconds"] == [2, 5, 10]


def test_vendor_retry_unknown(monkeypatch):
    _use(monkeypatch, REAL)
    with pytest.raises(RuntimeError, match="retry"):
        EC.vendor_retry("nova")


def test_tools_and_defaults(monkeypatch):
    _use(monkeypatch, REAL)
    assert EC.tools()["kipris"]["timeout_s"] == 30
    assert EC.defaults()["max_iterations"] == 10
