"""100.Nexus config — Settings 분기 전수 (invoke 단위).

대상: 100.Nexus/src/config.py. 200.DRO config 테스트와 동일 스타일.
분기 전수:
  _normalize_auth_mode : 대소문자 정규화 / None|빈문자열 → SECURE 기본 / 잘못된 값 ValueError
  JWT_SECRET_KEY       : OPEN+무secret → dev fallback / OPEN+given 유지 / SECURE 무주입 유지
  is_open              : OPEN True / SECURE False
  CM_URL               : topology service_url('cm') derive

CM_URL property 는 venezia_topology 가 topology.yaml 을 읽어
derive — conftest 의 topology_env(autouse) 가 @deployment/topology.yaml 을 가리키고 lru_cache 초기화.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "100.Nexus"))

from src.config import _DEV_JWT_FALLBACK, Settings  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """env-var 가 Settings() 기본 분기를 오염시키지 않도록 관련 키 제거."""
    for key in (
        "AUTH_MODE",
        "JWT_SECRET_KEY",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "NAVER_CLIENT_ID",
        "NAVER_CLIENT_SECRET",
        "KAKAO_CLIENT_ID",
        "KAKAO_CLIENT_SECRET",
    ):
        monkeypatch.delenv(key, raising=False)


# ── _DEV_JWT_FALLBACK 상수 ────────────────────────────────────────────────────


def test_dev_jwt_fallback_constant():
    assert _DEV_JWT_FALLBACK == "dev-only-jwt-secret-NOT-FOR-PRODUCTION-USE"


# ── _normalize_auth_mode: 대소문자 정규화 ─────────────────────────────────────


def test_auth_mode_lowercase_normalized_to_upper():
    s = Settings(AUTH_MODE="open")
    assert s.AUTH_MODE == "OPEN"


def test_auth_mode_mixed_case_normalized():
    s = Settings(AUTH_MODE="Secure")
    assert s.AUTH_MODE == "SECURE"


def test_auth_mode_already_upper_unchanged():
    s = Settings(AUTH_MODE="OPEN")
    assert s.AUTH_MODE == "OPEN"


# ── _normalize_auth_mode: 기본값 (빈 문자열 → SECURE) ─────────────────────────


def test_auth_mode_empty_string_defaults_to_secure():
    s = Settings(AUTH_MODE="")
    assert s.AUTH_MODE == "SECURE"


def test_auth_mode_default_is_secure():
    s = Settings()
    assert s.AUTH_MODE == "SECURE"


# ── _normalize_auth_mode: 잘못된 값 → ValueError (ValidationError 래핑) ────────


def test_auth_mode_invalid_raises():
    with pytest.raises(ValidationError) as exc:
        Settings(AUTH_MODE="bogus")
    assert "AUTH_MODE must be OPEN|SECURE" in str(exc.value)
    assert "BOGUS" in str(exc.value)  # upper 정규화 후 reject


def test_auth_mode_whitespace_invalid_raises():
    with pytest.raises(ValidationError):
        Settings(AUTH_MODE="op en")


# ── JWT_SECRET_KEY fallback 분기 ──────────────────────────────────────────────


def test_open_without_secret_injects_dev_fallback():
    s = Settings(AUTH_MODE="open")
    assert s.JWT_SECRET_KEY == _DEV_JWT_FALLBACK


def test_open_with_given_secret_kept():
    s = Settings(AUTH_MODE="open", JWT_SECRET_KEY="given-secret")
    assert s.JWT_SECRET_KEY == "given-secret"


def test_secure_without_secret_stays_empty():
    s = Settings(AUTH_MODE="secure")
    assert s.JWT_SECRET_KEY == ""


def test_secure_with_secret_kept():
    s = Settings(AUTH_MODE="secure", JWT_SECRET_KEY="x")
    assert s.JWT_SECRET_KEY == "x"


# ── is_open property ──────────────────────────────────────────────────────────


def test_is_open_true_when_open():
    assert Settings(AUTH_MODE="open").is_open is True


def test_is_open_false_when_secure():
    assert Settings(AUTH_MODE="secure").is_open is False


# ── CM_URL property (topology derive) ─────────────────────────────────────────


def test_cm_url_derived_from_topology():
    assert Settings().CM_URL == "http://cm:59400"
