"""100.Nexus auth — federated OAuth2 + 세션 JWT + 식별 레이어 (invoke 단위).

대상: 100.Nexus/src/auth.py. user_id ⊥ JWT ⊥ provider sub 철칙.

분기 전수:
  _Provider.authorization_url       : client.get_authorization_url 위임
  _Provider.exchange                : sync profile / async profile 둘 다
  provider_redirect_uri             : topology 파생 콜백 URL
  _google_profile                   : _google.get_profile 위임 (sub/email/name)
  _naver_profile / _kakao_profile   : httpx.AsyncClient.get → response 파싱
  get_provider                      : 존재 / 미지원(404)
  make_state / verify_state         : round-trip / 변조(400)
  resolve_or_mint_user_id           : identity hit / 신규 mint
  link_provider                     : 신규 / 다른 user 충돌(409) / 같은 user 중복(patch 안 함)
  unlink_provider                   : providers 에서 제거
  create_access_token / create_refresh_token / decode_token : round-trip / 만료 / 위조 / typ(401)
  make_pkce / sign_pkce / verify_pkce : round-trip / state 불일치(400) / 변조(400)
  get_current_user                  : OPEN 고정 / SECURE 무쿠키(401) / SECURE 유효 / refresh 거부(401)
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import jwt
import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "100.Nexus"))

from fastapi import HTTPException  # noqa: E402

import src.auth as auth  # noqa: E402
from src.auth import (  # noqa: E402
    OPEN_USER_ID,
    SUPPORTED_PROVIDERS,
    _Provider,
    _google_profile,
    _kakao_profile,
    _naver_profile,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    get_provider,
    link_provider,
    make_pkce,
    make_state,
    provider_redirect_uri,
    resolve_or_mint_user_id,
    sign_pkce,
    unlink_provider,
    verify_pkce,
    verify_state,
)
from src.config import settings  # noqa: E402

_SECRET = "unit-test-secret-key-distinct-from-default"  # nosec B105
_USER = "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def secure(monkeypatch):
    """AUTH_MODE=SECURE + 알려진 JWT secret (encode/decode 동일 키)."""
    monkeypatch.setattr(settings, "AUTH_MODE", "SECURE")
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", _SECRET)
    assert settings.is_open is False
    yield


@pytest.fixture
def open_mode(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_MODE", "OPEN")
    assert settings.is_open is True
    yield


# ── _Provider.authorization_url ───────────────────────────────────────────────


def test_provider_authorization_url_delegates():
    """client.get_authorization_url 에 redirect_uri/state/scope 전달, 반환값 그대로."""
    captured: dict[str, Any] = {}

    class _Client:
        async def get_authorization_url(
            self, redirect_uri, state, scope, code_challenge, code_challenge_method
        ):
            captured.update(
                redirect_uri=redirect_uri,
                state=state,
                scope=scope,
                code_challenge=code_challenge,
                code_challenge_method=code_challenge_method,
            )
            return "https://provider/authorize?x=1"

    p = _Provider("google", _Client(), ["openid", "email"], lambda t: ("s", None, None))
    url = asyncio.run(p.authorization_url("st-123", "challenge-xyz"))
    assert url == "https://provider/authorize?x=1"
    assert captured["state"] == "st-123"
    assert captured["scope"] == ["openid", "email"]
    assert captured["redirect_uri"] == provider_redirect_uri("google")
    assert captured["code_challenge"] == "challenge-xyz"
    assert captured["code_challenge_method"] == "S256"


# ── _Provider.exchange ────────────────────────────────────────────────────────


def test_provider_exchange_sync_profile():
    """profile_async=False → sync profile 호출 경로."""

    class _Client:
        async def get_access_token(self, code, redirect_uri, code_verifier):
            assert code == "code-1"
            assert redirect_uri == provider_redirect_uri("kakao")
            assert code_verifier == "verifier-1"
            return {"access_token": "tok-abc"}

    def _sync_profile(access_token: str):
        assert access_token == "tok-abc"
        return ("sub-1", "e@x", "name")

    p = _Provider("kakao", _Client(), [], _sync_profile, profile_async=False)
    assert asyncio.run(p.exchange("code-1", "verifier-1")) == ("sub-1", "e@x", "name")


def test_provider_exchange_async_profile():
    """profile_async=True → coroutine profile 호출 경로."""

    class _Client:
        async def get_access_token(self, code, redirect_uri, code_verifier):
            return {"access_token": "tok-xyz"}

    async def _async_profile(access_token: str):
        assert access_token == "tok-xyz"
        return ("sub-2", None, None)

    p = _Provider("naver", _Client(), [], _async_profile, profile_async=True)
    assert asyncio.run(p.exchange("code-2", "verifier-2")) == ("sub-2", None, None)


# ── provider_redirect_uri ─────────────────────────────────────────────────────


def test_provider_redirect_uri_shape():
    uri = provider_redirect_uri("naver")
    assert uri.endswith("/api/v1/user/auth/naver/callback")
    assert uri.startswith("http")


# ── _google_profile ───────────────────────────────────────────────────────────


def test_google_profile(monkeypatch):
    """_google.get_profile → (str(sub), email, name)."""
    monkeypatch.setattr(
        auth._google,
        "get_profile",
        AsyncMock(return_value={"sub": 12345, "email": "g@x", "name": "G"}),
    )
    assert asyncio.run(_google_profile("at")) == ("12345", "g@x", "G")


def test_google_profile_missing_optional(monkeypatch):
    """email/name 누락 → None."""
    monkeypatch.setattr(auth._google, "get_profile", AsyncMock(return_value={"sub": "abc"}))
    assert asyncio.run(_google_profile("at")) == ("abc", None, None)


# ── _naver_profile / _kakao_profile (httpx.AsyncClient monkeypatch) ───────────


class _FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload
        self.raised = False

    def raise_for_status(self) -> None:
        self.raised = True

    def json(self) -> Any:
        return self._payload


class _FakeClient:
    """httpx.AsyncClient(timeout=...) 대체 — async context manager + .get."""

    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.requested: dict[str, Any] = {}

    def __call__(self, *args, **kwargs):
        # auth.py 가 httpx.AsyncClient(timeout=15) 로 새 인스턴스 생성 → 이 호출이 그것.
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers=None):
        self.requested.update(url=url, headers=headers)
        return self._response


def test_naver_profile(monkeypatch):
    resp = _FakeResponse({"response": {"id": 777, "email": "n@x", "name": "N"}})
    fake = _FakeClient(resp)
    monkeypatch.setattr(auth.httpx, "AsyncClient", fake)
    assert asyncio.run(_naver_profile("nav-tok")) == ("777", "n@x", "N")
    assert resp.raised is True
    assert fake.requested["url"] == "https://openapi.naver.com/v1/nid/me"
    assert fake.requested["headers"]["Authorization"] == "Bearer nav-tok"


def test_naver_profile_name_falls_back_to_nickname(monkeypatch):
    """name 없으면 nickname. json() None 이면 {} 처리."""
    resp = _FakeResponse({"response": {"id": "z", "nickname": "nick"}})
    monkeypatch.setattr(auth.httpx, "AsyncClient", _FakeClient(resp))
    assert asyncio.run(_naver_profile("t")) == ("z", None, "nick")


def test_naver_profile_empty_json(monkeypatch):
    """r.json() → None → (None or {}).get('response', {}) → {} 빈 response."""
    resp = _FakeResponse(None)
    monkeypatch.setattr(auth.httpx, "AsyncClient", _FakeClient(resp))
    with pytest.raises(KeyError):
        asyncio.run(_naver_profile("t"))  # resp['id'] KeyError — 빈 response 경로 커버


def test_kakao_profile(monkeypatch):
    resp = _FakeResponse(
        {
            "id": 999,
            "kakao_account": {
                "email": "k@x",
                "profile": {"nickname": "kk"},
            },
        }
    )
    fake = _FakeClient(resp)
    monkeypatch.setattr(auth.httpx, "AsyncClient", fake)
    assert asyncio.run(_kakao_profile("kk-tok")) == ("999", "k@x", "kk")
    assert resp.raised is True
    assert fake.requested["url"] == "https://kapi.kakao.com/v2/user/me"


def test_kakao_profile_no_account(monkeypatch):
    """kakao_account / profile 누락 → email None, nickname None. body json None → {}."""
    resp = _FakeResponse({"id": "iid"})
    monkeypatch.setattr(auth.httpx, "AsyncClient", _FakeClient(resp))
    assert asyncio.run(_kakao_profile("t")) == ("iid", None, None)


def test_kakao_profile_account_present_profile_none(monkeypatch):
    """kakao_account 있으나 profile None → (acct.get('profile') or {}) 분기."""
    resp = _FakeResponse({"id": 1, "kakao_account": {"email": "e", "profile": None}})
    monkeypatch.setattr(auth.httpx, "AsyncClient", _FakeClient(resp))
    assert asyncio.run(_kakao_profile("t")) == ("1", "e", None)


# ── get_provider ──────────────────────────────────────────────────────────────


def test_get_provider_known():
    for name in SUPPORTED_PROVIDERS:
        p = get_provider(name)
        assert p.name == name


def test_get_provider_unknown_404():
    with pytest.raises(HTTPException) as ei:
        get_provider("github")
    assert ei.value.status_code == 404
    assert "github" in ei.value.detail


# ── make_state / verify_state ─────────────────────────────────────────────────


def test_make_and_verify_state_roundtrip():
    state = make_state()
    assert isinstance(state, str)
    verify_state(state)  # raise 없음


def test_verify_state_tampered_400():
    state = make_state()
    tampered = state[:-1] + ("A" if state[-1] != "A" else "B")
    with pytest.raises(HTTPException) as ei:
        verify_state(tampered)
    assert ei.value.status_code == 400
    assert "OAuth state" in ei.value.detail


def test_verify_state_garbage_400():
    with pytest.raises(HTTPException) as ei:
        verify_state("not-a-signed-state")
    assert ei.value.status_code == 400


# ── resolve_or_mint_user_id ───────────────────────────────────────────────────


def test_resolve_existing_identity_hit():
    cm = AsyncMock()
    cm.get_identity = AsyncMock(return_value={"user_id": "existing-uid"})
    uid = asyncio.run(resolve_or_mint_user_id(cm, "google", "sub-1"))
    assert uid == "existing-uid"
    cm.get_identity.assert_awaited_once_with("google", "sub-1")
    cm.put_identity.assert_not_called()
    cm.put_profile.assert_not_called()


def test_resolve_mint_new_when_none():
    cm = AsyncMock()
    cm.get_identity = AsyncMock(return_value=None)
    uid = asyncio.run(resolve_or_mint_user_id(cm, "naver", "sub-x"))
    assert isinstance(uid, str) and uid
    cm.put_identity.assert_awaited_once_with("naver", "sub-x", uid)
    cm.put_profile.assert_awaited_once()
    prof = cm.put_profile.await_args.args[1]
    assert prof["user_id"] == uid
    assert prof["nickname"] == f"발명가-{uid[:6]}"
    assert prof["providers"] == [{"provider": "naver", "sub": "sub-x"}]
    assert "created_at" in prof


def test_resolve_mint_new_when_record_without_user_id():
    """rec 는 있으나 user_id 키 없음 → mint 경로 (rec.get('user_id') falsy)."""
    cm = AsyncMock()
    cm.get_identity = AsyncMock(return_value={"other": 1})
    uid = asyncio.run(resolve_or_mint_user_id(cm, "kakao", "s"))
    cm.put_identity.assert_awaited_once_with("kakao", "s", uid)


# ── link_provider ─────────────────────────────────────────────────────────────


def test_link_provider_new_appends():
    cm = AsyncMock()
    cm.get_identity = AsyncMock(return_value=None)
    cm.get_profile = AsyncMock(return_value={"providers": [{"provider": "google", "sub": "g1"}]})
    asyncio.run(link_provider(cm, "uid-1", "naver", "n1"))
    cm.put_identity.assert_awaited_once_with("naver", "n1", "uid-1")
    cm.patch_profile.assert_awaited_once()
    ops = cm.patch_profile.await_args.args[1]
    assert ops[0]["op"] == "add"
    assert ops[0]["path"] == "/providers"
    assert {"provider": "naver", "sub": "n1"} in ops[0]["value"]


def test_link_provider_conflict_409():
    """이미 다른 user 에 연결된 provider → 409."""
    cm = AsyncMock()
    cm.get_identity = AsyncMock(return_value={"user_id": "other-uid"})
    with pytest.raises(HTTPException) as ei:
        asyncio.run(link_provider(cm, "uid-1", "naver", "n1"))
    assert ei.value.status_code == 409
    cm.put_identity.assert_not_called()


def test_link_provider_same_user_no_conflict_no_dup():
    """이미 같은 user 에 연결 + providers 에 이미 존재 → patch 안 함."""
    cm = AsyncMock()
    cm.get_identity = AsyncMock(return_value={"user_id": "uid-1"})
    cm.get_profile = AsyncMock(return_value={"providers": [{"provider": "naver", "sub": "n1"}]})
    asyncio.run(link_provider(cm, "uid-1", "naver", "n1"))
    cm.put_identity.assert_awaited_once_with("naver", "n1", "uid-1")
    cm.patch_profile.assert_not_called()


def test_link_provider_profile_none_defaults():
    """get_profile None → {} → providers [] → append."""
    cm = AsyncMock()
    cm.get_identity = AsyncMock(return_value=None)
    cm.get_profile = AsyncMock(return_value=None)
    asyncio.run(link_provider(cm, "uid-1", "kakao", "k1"))
    cm.patch_profile.assert_awaited_once()
    ops = cm.patch_profile.await_args.args[1]
    assert ops[0]["value"] == [{"provider": "kakao", "sub": "k1"}]


# ── unlink_provider ───────────────────────────────────────────────────────────


def test_unlink_provider_removes():
    cm = AsyncMock()
    cm.get_profile = AsyncMock(
        return_value={
            "providers": [
                {"provider": "google", "sub": "g1"},
                {"provider": "naver", "sub": "n1"},
            ]
        }
    )
    asyncio.run(unlink_provider(cm, "uid-1", "naver"))
    cm.patch_profile.assert_awaited_once()
    ops = cm.patch_profile.await_args.args[1]
    assert ops[0]["value"] == [{"provider": "google", "sub": "g1"}]
    # disconnect = 그 provider 의 로그인 인덱스도 폐기 (소유권 확인 — 재발급 매핑 오삭제 방지)
    cm.delete_identity.assert_awaited_once_with("naver", "n1", expected_user_id="uid-1")


def test_unlink_provider_profile_none_defaults():
    """get_profile None → providers [] → 빈 value patch + identity 삭제 없음."""
    cm = AsyncMock()
    cm.get_profile = AsyncMock(return_value=None)
    asyncio.run(unlink_provider(cm, "uid-1", "google"))
    ops = cm.patch_profile.await_args.args[1]
    assert ops[0]["value"] == []
    cm.delete_identity.assert_not_awaited()


def test_unlink_provider_delete_failure_skips_profile_patch():
    # identity 삭제(보안 핵심)가 먼저 + 실패 시 예외 전파 + profile **미패치** →
    # "해제됨 표기됐는데 매핑 남아 재로그인 복구"되는 부분실패 구멍 차단 (재시도로 수렴).
    cm = AsyncMock()
    cm.get_profile = AsyncMock(return_value={"providers": [{"provider": "naver", "sub": "n1"}]})
    cm.delete_identity = AsyncMock(side_effect=RuntimeError("cm down"))
    with pytest.raises(RuntimeError):
        asyncio.run(unlink_provider(cm, "uid-1", "naver"))
    cm.patch_profile.assert_not_awaited()


# ── create_access_token / create_refresh_token / decode_token ────────────────


def test_access_token_roundtrip(secure):
    token = create_access_token(_USER)
    claims = decode_token(token)  # default expected_typ="access"
    assert claims["sub"] == _USER and claims["typ"] == "access"
    assert "exp" in claims and "iat" in claims


def test_refresh_token_roundtrip(secure):
    token = create_refresh_token(_USER, "fam-1", "jti-1")
    claims = decode_token(token, expected_typ="refresh")
    assert claims["sub"] == _USER and claims["typ"] == "refresh"
    assert claims["fid"] == "fam-1" and claims["jti"] == "jti-1"


def test_decode_token_wrong_typ_401(secure):
    """access 를 refresh 자리에 decode → 401 Wrong token type (교차사용 차단)."""
    access = create_access_token(_USER)
    with pytest.raises(HTTPException) as ei:
        decode_token(access, expected_typ="refresh")
    assert ei.value.status_code == 401
    assert ei.value.detail == "Wrong token type"


def test_jwt_secret_fail_close_secure_empty(secure, monkeypatch):
    """SECURE + JWT secret 미주입 → fail-close 503 (빈 키 서명/검증으로 인증 우회 차단)."""
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "")
    with pytest.raises(HTTPException) as ei:
        create_access_token(_USER)
    assert ei.value.status_code == 503
    with pytest.raises(HTTPException) as ei2:
        decode_token("any-token")
    assert ei2.value.status_code == 503


def test_decode_token_expired_401(secure, monkeypatch):
    """ACCESS_TOKEN_EXPIRE_MINUTES 음수 → 즉시 만료 → 401 Token expired."""
    monkeypatch.setattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", -5)
    expired = create_access_token(_USER)
    with pytest.raises(HTTPException) as ei:
        decode_token(expired)
    assert ei.value.status_code == 401
    assert ei.value.detail == "Token expired"
    assert "expired" in ei.value.headers["WWW-Authenticate"]


def test_decode_token_wrong_secret_401(secure):
    forged = jwt.encode(  # nosemgrep
        {
            "sub": _USER,
            "typ": "access",
            "exp": datetime.now(UTC) + timedelta(minutes=10),
            "iat": datetime.now(UTC),
        },
        "some-other-secret",
        algorithm=settings.JWT_ALGORITHM,
    )
    with pytest.raises(HTTPException) as ei:
        decode_token(forged)
    assert ei.value.status_code == 401
    assert ei.value.detail == "Invalid token"
    assert ei.value.headers["WWW-Authenticate"] == 'Bearer error="invalid_token"'


def test_decode_token_malformed_401(secure):
    with pytest.raises(HTTPException) as ei:
        decode_token("not.a.jwt")
    assert ei.value.status_code == 401
    assert ei.value.detail == "Invalid token"


# ── PKCE (make / sign / verify) ──────────────────────────────────────────────


def test_pkce_roundtrip(secure):
    verifier, challenge = make_pkce()
    assert verifier and challenge and verifier != challenge
    signed = sign_pkce(verifier, "state-1")
    assert verify_pkce(signed, "state-1") == verifier


def test_pkce_state_mismatch_400(secure):
    verifier, _ = make_pkce()
    signed = sign_pkce(verifier, "state-1")
    with pytest.raises(HTTPException) as ei:
        verify_pkce(signed, "state-OTHER")
    assert ei.value.status_code == 400


def test_pkce_tampered_400(secure):
    with pytest.raises(HTTPException) as ei:
        verify_pkce("not-a-signed-value", "state-1")
    assert ei.value.status_code == 400


# ── get_current_user ──────────────────────────────────────────────────────────


def test_get_current_user_open_fixed(open_mode):
    assert get_current_user(token=None) == {"user_id": OPEN_USER_ID}


def test_get_current_user_secure_no_cookie_401(secure):
    with pytest.raises(HTTPException) as ei:
        get_current_user(token=None)
    assert ei.value.status_code == 401
    assert ei.value.detail == "Authentication required"


def test_get_current_user_secure_valid(secure):
    out = get_current_user(token=create_access_token(_USER))
    assert out == {"user_id": _USER}


def test_get_current_user_secure_refresh_rejected_401(secure):
    """refresh 토큰을 access 쿠키 자리에 → typ 불일치 401 (교차사용 차단)."""
    with pytest.raises(HTTPException) as ei:
        get_current_user(token=create_refresh_token(_USER, "f", "j"))
    assert ei.value.status_code == 401
