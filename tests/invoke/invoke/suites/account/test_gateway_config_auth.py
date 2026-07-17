"""100.Nexus gateway 신규 spot — config.DRO_URL + auth.user_id_from_token (invoke 단위).

대상:
  100.Nexus/src/config.py line 74 : Settings().DRO_URL → venezia_topology service_url('dro')
  100.Nexus/src/auth.py           : user_id_from_token(WS access 쿠키 → user_id)

분기 전수 (user_id_from_token):
  OPEN                      : 토큰 None 이어도 고정 OPEN_USER_ID
  SECURE + 유효 토큰        : create_access_token mint → decode 후 sub
  SECURE + None 토큰        : None
  SECURE + 빈 문자열 토큰   : None  (falsy → not token 분기)
  SECURE + 위조/만료 토큰   : None  (decode_token 의 HTTPException → except 흡수)

settings 분기는 기존 auth suite 패턴대로 monkeypatch.setattr(settings, ...) 로 제어.
topology 파생(DRO_URL)은 conftest 의 topology_env(autouse) 가 @deployment/topology.yaml 가리킴.
sync 함수만 — asyncio 불필요.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "100.Nexus"))

from src.auth import (  # noqa: E402
    OPEN_USER_ID,
    create_access_token,
    user_id_from_token,
)
from src.config import Settings, settings  # noqa: E402

_SECRET = "gateway-unit-secret-distinct"  # nosec B105
_USER = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


# ── config.DRO_URL property (topology derive) ─────────────────────────────────


def test_dro_url_derived_from_topology():
    """DRO_URL == venezia_topology service_url('dro') (@deployment/topology.yaml)."""
    from venezia_topology import service_url

    assert Settings().DRO_URL == service_url("dro")


def test_dro_url_concrete_value():
    assert Settings().DRO_URL == "http://dro:59200"


# ── auth.user_id_from_token — fixtures ────────────────────────────────────────


@pytest.fixture
def secure(monkeypatch):
    """AUTH_MODE=SECURE + 알려진 JWT secret (mint/검증 동일 키)."""
    monkeypatch.setattr(settings, "AUTH_MODE", "SECURE")
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", _SECRET)
    assert settings.is_open is False
    yield


@pytest.fixture
def open_mode(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_MODE", "OPEN")
    assert settings.is_open is True
    yield


# ── OPEN: 토큰 무관 고정 user_id (line 271-272) ───────────────────────────────


def test_open_returns_fixed_user_id_with_none(open_mode):
    assert user_id_from_token(None) == OPEN_USER_ID


def test_open_returns_fixed_user_id_with_token(open_mode):
    assert user_id_from_token("anything") == OPEN_USER_ID


# ── SECURE + 유효 토큰 → sub (line 275-276) ───────────────────────────────────


def test_secure_valid_token_returns_sub(secure):
    token = create_access_token(_USER)
    assert user_id_from_token(token) == _USER


# ── SECURE + None / 빈 토큰 → None (line 273-274) ─────────────────────────────


def test_secure_none_token_returns_none(secure):
    assert user_id_from_token(None) is None


def test_secure_empty_token_returns_none(secure):
    assert user_id_from_token("") is None


# ── SECURE + 위조/만료 토큰 → None (line 277-278 HTTPException 흡수) ────────────


def test_secure_invalid_token_returns_none(secure):
    assert user_id_from_token("not-a-jwt") is None


def test_secure_wrong_secret_token_returns_none(secure):
    """다른 키로 서명 → decode_token PyJWTError → HTTPException → None."""
    forged = jwt.encode(  # nosemgrep
        {"sub": _USER, "exp": datetime.now(UTC) + timedelta(minutes=5)},
        "a-completely-different-key",
        algorithm=settings.JWT_ALGORITHM,
    )
    assert user_id_from_token(forged) is None


def test_secure_expired_token_returns_none(secure):
    """만료 토큰 → decode_token ExpiredSignatureError → HTTPException → None."""
    expired = jwt.encode(  # nosemgrep
        {"sub": _USER, "exp": datetime.now(UTC) - timedelta(minutes=5)},
        _SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    assert user_id_from_token(expired) is None
