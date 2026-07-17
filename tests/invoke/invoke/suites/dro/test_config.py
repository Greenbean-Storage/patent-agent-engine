"""200.DRO config — Settings 전수 (invoke 단위).

대상: 200.DRO/src/config.py. DRO 는 auth 없는 순수 내부 executor —
JWT_SECRET_KEY / AUTH_MODE / is_open / ENGINE_MODE 모두 cutover 에서 제거됨.
현재 남은 표면:
  PIPELINES_DIR / DISPATCH_TIMEOUT_S / BUSY_BACKOFF_S 기본값 + override
  LLM_MODE = default_factory=venezia_deployment.llm() (마운트 profile). 인자·env·파일 없으면
    fallback PRODUCTION. invoke 는 Settings(LLM_MODE=...) 또는 env 로 명시 (1b-C).
  CM_URL property == service_url('cm')
  ACTOR_URL property == service_url('actor') (unified 단일 actor — 구 actor_urls 후보 풀 폐기)

CM_URL·ACTOR_URL 은 venezia_topology 가 topology.yaml 을 읽어 derive — host 에선
TOPOLOGY_FILE env 필요. @deployment/topology.yaml 을 가리키고 lru_cache 초기화.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "200.DRO"))

from src.config import Settings, settings  # noqa: E402


@pytest.fixture
def topology_env(monkeypatch):
    """CM_URL / ACTOR_URL property 는 topology.yaml 의존 — host TOPOLOGY_FILE env 설정."""
    import venezia_topology as vt

    monkeypatch.setenv("TOPOLOGY_FILE", str(ROOT / "@deployment" / "topology.yaml"))
    vt._load.cache_clear()
    yield
    vt._load.cache_clear()


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """env-var/profile 이 Settings() 기본 분기를 오염시키지 않도록 격리.

    1b: LLM_MODE 는 default_factory=venezia_deployment.llm() — 파일·인자·env 없으면
    fallback(PRODUCTION). DEPLOYMENT_FILE 제거 + runtime cache clear 로 fallback 결정성 확보.
    """
    import venezia_deployment.runtime as vd

    for key in (
        "PIPELINES_DIR",
        "DISPATCH_TIMEOUT_S",
        "BUSY_BACKOFF_S",
        "LLM_MODE",
        "DEPLOYMENT_FILE",
    ):
        monkeypatch.delenv(key, raising=False)
    vd._load.cache_clear()
    yield
    vd._load.cache_clear()


# ── 기본값 (env 미주입 시 BaseSettings field default) ─────────────────────────


def test_pipelines_dir_default():
    assert Settings().PIPELINES_DIR == "/pipelines"


def test_dispatch_timeout_default():
    assert Settings().DISPATCH_TIMEOUT_S == 1200.0


def test_busy_backoff_default():
    assert Settings().BUSY_BACKOFF_S == 1.0


def test_llm_mode_default_production():
    # 1b: 인자·env·profile 없음 → default_factory → fallback = PRODUCTION (knobs.yaml default llm=real).
    assert Settings().LLM_MODE == "PRODUCTION"


# ── override (생성자 kwarg) ──────────────────────────────────────────────────


def test_pipelines_dir_override():
    assert Settings(PIPELINES_DIR="/custom").PIPELINES_DIR == "/custom"


def test_dispatch_timeout_override():
    assert Settings(DISPATCH_TIMEOUT_S=5.0).DISPATCH_TIMEOUT_S == 5.0


def test_busy_backoff_override():
    assert Settings(BUSY_BACKOFF_S=2.5).BUSY_BACKOFF_S == 2.5


def test_llm_mode_override():
    assert Settings(LLM_MODE="PRODUCTION").LLM_MODE == "PRODUCTION"


# ── env override (model_config env_file/extra) ───────────────────────────────


def test_llm_mode_env_override(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "PRODUCTION")
    assert Settings().LLM_MODE == "PRODUCTION"


def test_extra_env_ignored(monkeypatch):
    """model_config extra='ignore' — 미정의 env 키는 무시 (raise 안 함)."""
    monkeypatch.setenv("UNKNOWN_DRO_KEY", "whatever")
    assert Settings().PIPELINES_DIR == "/pipelines"


# ── removed surface — auth/engine 필드는 더 이상 존재하지 않음 ─────────────────


def test_no_auth_or_engine_fields():
    s = Settings()
    for removed in ("JWT_SECRET_KEY", "AUTH_MODE", "ENGINE_MODE", "is_open"):
        assert not hasattr(s, removed)


# ── CM_URL property (topology derive) ─────────────────────────────────────────


def test_cm_url_derived_from_topology(topology_env):
    from venezia_topology import service_url

    assert Settings().CM_URL == "http://cm:59400"
    assert Settings().CM_URL == service_url("cm")


# ── ACTOR_URL property (topology derive — unified 단일 actor 직결) ─────────────


def test_actor_url_derived_from_topology(topology_env):
    from venezia_topology import service_url

    assert Settings().ACTOR_URL == "http://actor:59300"
    assert Settings().ACTOR_URL == service_url("actor")


# ── 모듈 레벨 singleton ───────────────────────────────────────────────────────


def test_module_singleton_is_settings_instance():
    assert isinstance(settings, Settings)
