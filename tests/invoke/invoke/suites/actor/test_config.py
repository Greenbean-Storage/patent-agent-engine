"""300.Actor config — Settings 분기/CM_URL 전수 (invoke 단위).

대상: 300.Actor/src/config.py:Settings
  - 기본값 (ACTOR_ID/FIXTURE_PATH/KIPRIS_*).
  - LLM_MODE = default_factory=venezia_deployment.llm() (마운트 profile). 파일·env 없으면 fallback PRODUCTION.
  - persona 수락 집합은 Settings 에 없음 — engine.config `personas` (구 ACTOR_PERSONAS env 폐기, unified).
  - CM_URL property → venezia_topology.service_url("cm") (topology.yaml derive).
  - env var override (LLM_MODE).

Settings 는 BaseSettings 라 env 를 읽는다 — 명시 인자/monkeypatch.setenv 로 분기 강제.
CM_URL 은 topology.yaml 을 읽으므로 TOPOLOGY_FILE env 로 repo 루트를 가리키고 cache clear.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "300.Actor"))
sys.path.insert(0, str(ROOT / "shared"))

from src.config import Settings  # noqa: E402


@pytest.fixture
def topology_env(monkeypatch):
    """settings.CM_URL 는 venezia_topology 가 topology.yaml 을 읽어 derive — host 에선
    TOPOLOGY_FILE env 필요. @deployment/topology.yaml 을 가리키고 lru_cache 초기화."""
    import venezia_topology as vt

    monkeypatch.setenv("TOPOLOGY_FILE", str(ROOT / "@deployment" / "topology.yaml"))
    vt._load.cache_clear()
    yield
    vt._load.cache_clear()


@pytest.fixture(autouse=True)
def _isolate_deploy(monkeypatch):
    """1b: LLM_MODE default_factory=venezia_deployment.llm(). 인자·env·파일 없으면 fallback(PRODUCTION).
    DEPLOYMENT_FILE/LLM_MODE 제거 + runtime cache clear 로 결정성."""
    import venezia_deployment.runtime as vd

    monkeypatch.delenv("DEPLOYMENT_FILE", raising=False)
    monkeypatch.delenv("LLM_MODE", raising=False)
    vd._load.cache_clear()
    yield
    vd._load.cache_clear()


# ── 기본값 ──────────────────────────────────────────────────────────────────────


def test_defaults():
    s = Settings(_env_file=None)
    assert s.ACTOR_ID == "actor-unknown"
    # 1b: LLM_MODE = default_factory → 파일·env 없으면 fallback PRODUCTION (knobs.yaml default).
    assert s.LLM_MODE == "PRODUCTION"
    assert s.FIXTURE_PATH == "/app/data/llm-fixtures"
    assert s.KIPRIS_API_KEY == ""
    # KIPRIS 운영값(base_url/timeout/결과수/cache)은 engine.config 로 이동 — test_engine_config.py
    # persona 수락 집합도 env 아님 — engine.config personas (구 ACTOR_PERSONAS 폐기, unified)
    assert not hasattr(s, "ACTOR_PERSONAS")


# ── env override ────────────────────────────────────────────────────────────────


def test_env_override(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "PRODUCTION")
    monkeypatch.setenv("ACTOR_ID", "300.Actor")
    s = Settings(_env_file=None)
    assert s.LLM_MODE == "PRODUCTION"
    assert s.ACTOR_ID == "300.Actor"


# ── CM_URL property ───────────────────────────────────────────────────────────


def test_cm_url_derives_from_topology(topology_env):
    from venezia_topology import service_url

    s = Settings(_env_file=None)
    assert s.CM_URL == service_url("cm")
    # topology.yaml 의 cm: { host: cm, port: 59400 } → http://cm:59400
    assert s.CM_URL == "http://cm:59400"
