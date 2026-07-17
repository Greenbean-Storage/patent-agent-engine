"""Federated OAuth2 (Google / Naver / Kakao) + 우리 세션 JWT + 식별 레이어.

핵심 (설계 철칙: user_id ⊥ JWT, user_id ⊥ provider sub):
- provider 의 sub 는 issuer-scoped 식별자일 뿐 — 우리 user_id 가 아니다.
- 우리가 user_id(UUID) 를 자체 발급하고 `(provider, provider_sub) → user_id` 매핑을 CM(S3)에 영속.
- 우리 JWT(세션 토큰)는 **우리 user_id** 를 sub claim 으로 실음 (provider sub 아님).
  세션 저장소 없음(stateless).
- AUTH_MODE=OPEN → 인증 불요, 고정 user_id. SECURE → 우리 JWT 검증 → user_id.
- PII 0: 실명·이메일 저장 안 함. nickname(비-PII) 만 자동부여+수정.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import APIKeyCookie
from httpx_oauth.clients.google import GoogleOAuth2
from httpx_oauth.oauth2 import BaseOAuth2
from itsdangerous import BadSignature, TimestampSigner
from venezia_topology import service_url

from .config import settings

_cookie = APIKeyCookie(name=settings.ACCESS_COOKIE_NAME, auto_error=False)
_signer = TimestampSigner(settings.JWT_SECRET_KEY or "open-state", salt="oauth-state")
_pkce_signer = TimestampSigner(settings.JWT_SECRET_KEY or "open-state", salt="oauth-pkce")

# AUTH_MODE=OPEN 에서 쓰는 고정 user_id (provider 무관, 위조 불가 — 서버가 정함).
OPEN_USER_ID = "00000000-0000-0000-0000-00000000open"

SUPPORTED_PROVIDERS = ("google", "naver", "kakao")


# ---------------------------------------------------------------------------
# provider registry — 각 provider 의 OAuth2 client + profile 파서
# ---------------------------------------------------------------------------


class _Provider:
    """provider 1개의 OAuth2 흐름 + (sub, email, name) 추출."""

    def __init__(
        self,
        name: str,
        client: BaseOAuth2,
        scope: list[str],
        profile: Callable[[str], Any],  # sync 또는 async(coroutine) — profile_async 로 분기
        profile_async: bool = False,
    ) -> None:
        self.name = name
        self.client = client
        self.scope = scope
        self._profile = profile
        self._profile_async = profile_async

    async def authorization_url(self, state: str, code_challenge: str) -> str:
        return await self.client.get_authorization_url(
            redirect_uri=provider_redirect_uri(self.name),
            state=state,
            scope=self.scope,
            code_challenge=code_challenge,
            code_challenge_method="S256",
        )

    async def exchange(self, code: str, code_verifier: str) -> tuple[str, str | None, str | None]:
        """code(+PKCE verifier) → (provider_sub, email, name)."""
        token = await self.client.get_access_token(
            code, provider_redirect_uri(self.name), code_verifier=code_verifier
        )
        access_token = token["access_token"]
        if self._profile_async:
            return await self._profile(access_token)  # type: ignore[misc]
        return self._profile(access_token)


def provider_redirect_uri(provider: str) -> str:
    """provider 별 콜백 (서버측). 새 트리 경로 — /api/v1/user/auth/{provider}/callback."""
    return f"{service_url('nexus')}/api/v1/user/auth/{provider}/callback"


# -- Google (httpx-oauth 내장) --
_google = GoogleOAuth2(settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET)


async def _google_profile(access_token: str) -> tuple[str, str | None, str | None]:
    profile = await _google.get_profile(access_token)
    return str(profile["sub"]), profile.get("email"), profile.get("name")


# -- Naver / Kakao (OAuth2 generic + 수동 profile fetch) --
_naver_client = BaseOAuth2(
    settings.NAVER_CLIENT_ID,
    settings.NAVER_CLIENT_SECRET,
    "https://nid.naver.com/oauth2.0/authorize",
    "https://nid.naver.com/oauth2.0/token",
)
_kakao_client = BaseOAuth2(
    settings.KAKAO_CLIENT_ID,
    settings.KAKAO_CLIENT_SECRET,
    "https://kauth.kakao.com/oauth/authorize",
    "https://kauth.kakao.com/oauth/token",
)


async def _naver_profile(access_token: str) -> tuple[str, str | None, str | None]:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(
            "https://openapi.naver.com/v1/nid/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        r.raise_for_status()
        resp = (r.json() or {}).get("response", {})
    return str(resp["id"]), resp.get("email"), resp.get("name") or resp.get("nickname")


async def _kakao_profile(access_token: str) -> tuple[str, str | None, str | None]:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(
            "https://kapi.kakao.com/v2/user/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        r.raise_for_status()
        body = r.json() or {}
    acct = body.get("kakao_account", {}) or {}
    name = (acct.get("profile") or {}).get("nickname")
    return str(body["id"]), acct.get("email"), name


_PROVIDERS: dict[str, _Provider] = {
    "google": _Provider("google", _google, ["openid", "email", "profile"], _google_profile, True),
    "naver": _Provider("naver", _naver_client, [], _naver_profile, True),
    "kakao": _Provider(
        "kakao", _kakao_client, ["account_email", "profile_nickname"], _kakao_profile, True
    ),
}


def get_provider(provider: str) -> _Provider:
    p = _PROVIDERS.get(provider)
    if p is None:
        raise HTTPException(404, f"unknown provider {provider!r}. supported: {SUPPORTED_PROVIDERS}")
    return p


# ---------------------------------------------------------------------------
# OAuth state (CSRF protection)
# ---------------------------------------------------------------------------


def make_state() -> str:
    return _signer.sign(str(uuid.uuid4())).decode()


def verify_state(state: str, max_age: int = 600) -> None:
    try:
        _signer.unsign(state, max_age=max_age)
    except BadSignature as exc:
        raise HTTPException(400, "Invalid or expired OAuth state") from exc


# ---------------------------------------------------------------------------
# PKCE (S256) — verifier 는 /authorize 가 서명된 httpOnly 쿠키로 심고 콜백/connect 가 1회 consume
# ---------------------------------------------------------------------------


def make_pkce() -> tuple[str, str]:
    """(code_verifier, code_challenge[S256]). verifier = URL-safe 43-128 chars."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def sign_pkce(verifier: str, state: str) -> str:
    """verifier 를 state 에 바인딩해 서명 (nx_pkce 쿠키 값)."""
    return _pkce_signer.sign(f"{state}:{verifier}").decode()


def verify_pkce(signed: str, state: str, max_age: int = 600) -> str:
    """nx_pkce 쿠키 검증 + state 바인딩 확인 → verifier."""
    try:
        raw = _pkce_signer.unsign(signed, max_age=max_age).decode()
    except BadSignature as exc:
        raise HTTPException(400, "Invalid or expired PKCE") from exc
    bound_state, _, verifier = raw.partition(":")
    if bound_state != state or not verifier:
        raise HTTPException(400, "PKCE state mismatch")
    return verifier


# ---------------------------------------------------------------------------
# 식별 레이어 — (provider, sub) → 우리 user_id (CM 매핑). PII 0.
# ---------------------------------------------------------------------------


def _auto_nickname(user_id: str) -> str:
    return f"발명가-{user_id[:6]}"


async def resolve_or_mint_user_id(cm: Any, provider: str, provider_sub: str) -> str:
    """로그인: (provider, sub) → 우리 user_id. 없으면 신규 발급(=가입). PII 미저장.

    cm = CMClient. 첫 로그인이면 user_id(UUID) mint + identity 매핑 + profile(nickname) 생성.
    """
    rec = await cm.get_identity(provider, provider_sub)
    if rec and rec.get("user_id"):
        return str(rec["user_id"])
    user_id = str(uuid.uuid4())
    await cm.put_identity(provider, provider_sub, user_id)
    await cm.put_profile(
        user_id,
        {
            "user_id": user_id,
            "nickname": _auto_nickname(user_id),
            "providers": [{"provider": provider, "sub": provider_sub}],
            "created_at": datetime.now(UTC).isoformat(),
        },
    )
    return user_id


async def link_provider(cm: Any, user_id: str, provider: str, provider_sub: str) -> None:
    """명시적 연결(connect): 기존 user_id 에 다른 provider 추가."""
    existing = await cm.get_identity(provider, provider_sub)
    if existing and existing.get("user_id") not in (None, user_id):
        raise HTTPException(409, "이 provider 계정은 이미 다른 사용자에 연결됨")
    await cm.put_identity(provider, provider_sub, user_id)
    prof = await cm.get_profile(user_id) or {}
    providers = prof.get("providers") or []
    if not any(p.get("provider") == provider and p.get("sub") == provider_sub for p in providers):
        providers.append({"provider": provider, "sub": provider_sub})
        await cm.patch_profile(user_id, [{"op": "add", "path": "/providers", "value": providers}])


async def unlink_provider(cm: Any, user_id: str, provider: str) -> None:
    """연결 해제(disconnect): profile.providers 에서 제거 + 그 provider 의 로그인 인덱스(identity)
    삭제 → 이후 그 provider 재로그인은 매핑 없음 → 새 user_id(별개 계정), 기존 계정 복구 차단.
    멱등 (미연결이어도 안전)."""
    prof = await cm.get_profile(user_id) or {}
    all_providers = prof.get("providers") or []
    removed = [p for p in all_providers if p.get("provider") == provider]
    kept = [p for p in all_providers if p.get("provider") != provider]
    # 순서 = 보안 우선: 로그인 인덱스(identity) **먼저** 폐기 → profile 패치 나중.
    # 부분 실패 시 profile 만 stale(재시도로 수렴, delete 멱등) — "해제됐다 표기됐는데
    # 매핑이 남아 재로그인 복구"되는 구멍은 발생하지 않음.
    for p in removed:
        sub = p.get("sub")
        if sub:
            # 소유권 확인 삭제 — 재시도가 그 사이 재발급된(다른 user) 매핑을 지우지 않도록.
            await cm.delete_identity(provider, sub, expected_user_id=user_id)
    await cm.patch_profile(user_id, [{"op": "add", "path": "/providers", "value": kept}])


# ---------------------------------------------------------------------------
# 우리 세션 JWT (sub = 우리 user_id. provider sub 아님)
# ---------------------------------------------------------------------------


def _jwt_secret() -> str:
    """JWT 서명/검증 키. SECURE 인데 secret 미주입이면 fail-close(503) — 빈 키로 토큰
    위조·검증 우회(인증 bypass) 차단. OPEN 은 validator 가 dev fallback 주입(비어있지 않음)."""
    secret = settings.JWT_SECRET_KEY
    if not secret and not settings.is_open:
        raise HTTPException(status_code=503, detail="auth misconfigured: JWT secret missing")
    return secret


def create_access_token(user_id: str) -> str:
    """짧은 수명 access 토큰 (httpOnly 쿠키). sub=우리 user_id, typ=access. PII 없음."""
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": user_id,
        "typ": "access",
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        "iat": now,
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(user_id: str, family_id: str, jti: str) -> str:
    """긴 수명 refresh 토큰 (httpOnly 쿠키, 회전). family_id+jti 로 서버측 family 게이트(CM)."""
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": user_id,
        "typ": "refresh",
        "fid": family_id,
        "jti": jti,
        "exp": now + timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES),
        "iat": now,
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str, *, expected_typ: str = "access") -> dict[str, Any]:
    """JWT 검증 + typ 강제 (access 를 /refresh 에, refresh 를 API 에 교차사용 차단)."""
    secret = _jwt_secret()  # SECURE+빈 secret = fail-close (빈 키 검증 우회 차단)
    try:
        claims = jwt.decode(token, secret, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            401,
            "Token expired",
            headers={
                "WWW-Authenticate": 'Bearer error="invalid_token", error_description="expired"'
            },
        ) from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(
            401, "Invalid token", headers={"WWW-Authenticate": 'Bearer error="invalid_token"'}
        ) from exc
    if claims.get("typ") != expected_typ:
        raise HTTPException(
            401, "Wrong token type", headers={"WWW-Authenticate": 'Bearer error="invalid_token"'}
        )
    return claims


# ---------------------------------------------------------------------------
# FastAPI dependency — 매 요청 user_id 해석 (클라는 user_id 직접 안 보냄)
# ---------------------------------------------------------------------------


def get_current_user(
    token: str | None = Depends(_cookie),
) -> dict[str, Any]:
    """AUTH_MODE 분기 — access 토큰은 httpOnly 쿠키(nx_access)로 자동 첨부.

    OPEN: 토큰 불요 → 고정 user_id. SECURE: nx_access 쿠키 검증(typ=access) → {user_id}.
    어느 경우든 user_id 는 서버가 결정 (클라가 직접 안 보냄 → 위조 불가).
    """
    if settings.is_open:
        return {"user_id": OPEN_USER_ID}
    if not token:
        raise HTTPException(401, "Authentication required")
    claims = decode_token(token, expected_typ="access")
    return {"user_id": claims["sub"]}


def user_id_from_token(token: str | None) -> str | None:
    """WS access 쿠키(nx_access) → user_id. OPEN 이면 토큰 없어도 고정 user_id. SECURE 면 검증.

    client WS (thread/stream) handshake 에 자동 첨부된 nx_access 쿠키를 해석.
    Nexus 가 유일한 인증 지점 (DRO 는 인증 없음).
    """
    if settings.is_open:
        return OPEN_USER_ID
    if not token:
        return None
    try:
        return str(decode_token(token, expected_typ="access")["sub"])
    except HTTPException:
        return None
