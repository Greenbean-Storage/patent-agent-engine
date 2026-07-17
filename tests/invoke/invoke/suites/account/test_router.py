"""100.Nexus REST router — invoke 단위테스트 (≥99% line).

대상: 100.Nexus/src/router.py. FastAPI app 을 router 만으로 조립(main 의 secrets/AWS fetch 회피)
하고 errors.install 로 envelope handler 등록. get_current_user 는 dependency_overrides 로 mock,
CM 은 `src.router.get_cm_client` monkeypatch 로 대체. auth 헬퍼(get_provider/verify_state/exchange/
resolve_or_mint_user_id/create_access_token/create_refresh_token/link_provider/unlink_provider) 도 monkeypatch.

async 테스트는 기존 suite 패턴대로 동기 def 안에서 asyncio.run(...) 로 호출.

  info     : providers, attributions
  auth     : authorize, callback, connect(code/422), disconnect
  account  : info(_profile nickname/fallback), alias get, alias set(빈→422 / 정상)
  works    : new, brief(_progress dict/None/scores 변형 + item build except + skip 분기)
  work     : detail(manifest None→404 / 정상), rename(빈 title→422 / 정상=detail 재호출)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "100.Nexus"))

import httpx  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from src import errors  # noqa: E402
from src import router as router_mod  # noqa: E402
from src.auth import get_current_user  # noqa: E402
from src.router import _progress, router  # noqa: E402

_UID = "u-1"
_WORK = "work-1"


# ── fakes ──────────────────────────────────────────────────────────────────


class _FakeCM:
    """라우터가 호출하는 CM 메서드만 구현. 반환값을 attribute 로 주입."""

    def __init__(self, **rets) -> None:
        self._rets = rets
        self.patches: list[tuple] = []
        # works_brief 의 item-build except 분기용: get_context_manifest 가 특정 wid 에서 raise
        self.manifest_raise_for: set[str] = set()
        # Idempotency-Key 영속 store (C3) — in-memory round-trip
        self._idem: dict = {}
        self.session_calls = 0

    async def get_profile(self, user_id):
        return self._rets.get("profile")

    async def patch_profile(self, user_id, ops):
        self.patches.append(("profile", user_id, ops))
        # write_profile 가 updated_at 스탬프 → patch 결과에 새 updated_at (set_alias ETag 용)
        return {**(self._rets.get("profile") or {}), "updated_at": "ts-after"}

    async def create_session(self, user_id):
        self.session_calls += 1
        return self._rets.get("session", {})

    async def claim_idempotency(self, user_id, key):
        # 원자 선점 모사: done(완료기록) / in_flight(미완료 선점) / claimed(신규)
        rec = self._idem.get((user_id, key))
        if rec is not None:
            if rec.get("body") is not None:
                return ("done", rec)
            return ("in_flight", None)  # fake: staleness 미고려 (테스트 불요)
        self._idem[(user_id, key)] = {"claimed_at": "x"}
        return ("claimed", None)

    async def put_idempotency(self, user_id, key, record):
        self._idem[(user_id, key)] = record

    async def delete_idempotency(self, user_id, key):
        self._idem.pop((user_id, key), None)

    async def list_sessions(self, user_id):
        return self._rets.get("sessions")

    async def get_context_manifest(self, user_id, work_id):
        if work_id in self.manifest_raise_for:
            raise RuntimeError("boom")
        manifests = self._rets.get("manifests")
        if manifests is not None:
            return manifests.get(work_id)
        return self._rets.get("manifest")

    async def get_concept_maturity_model(self, user_id, work_id):
        return self._rets.get("maturity")

    async def patch_context_manifest(self, user_id, work_id, ops):
        self.patches.append(("manifest", user_id, work_id, ops))
        return {"ok": True}

    async def download_document(self, user_id, work_id, filename):
        return self._rets.get("doc_body")

    async def get_conversation(self, user_id, work_id):
        return self._rets.get("conversation")

    async def get_user_roadmap(self, user_id, work_id):
        return self._rets.get("roadmap")

    async def put_refresh_family(self, user_id, family_id, jti):
        self.patches.append(("rf_put", user_id, family_id, jti))

    async def rotate_refresh_family(self, user_id, family_id, expected_jti, new_jti):
        self.patches.append(("rf_rotate", user_id, family_id, expected_jti, new_jti))
        return self._rets.get("rotate_result", "rotated")

    async def revoke_refresh_family(self, user_id, family_id):
        self.patches.append(("rf_revoke", user_id, family_id))


class _FakeProvider:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def authorization_url(self, state, code_challenge):
        self.calls.append(("authz", state, code_challenge))
        return f"https://auth.example/login?state={state}"

    async def exchange(self, code, code_verifier):
        self.calls.append(("exchange", code, code_verifier))
        return ("psub-9", "ignored@example.com", "ignored-name")


def _build_app(cm, monkeypatch, *, user=None):
    """router 만으로 가벼운 app 조립 + cm/auth dependency mock."""
    app = FastAPI()
    errors.install(app)
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: (user or {"user_id": _UID})
    monkeypatch.setattr(router_mod, "get_cm_client", lambda: cm)
    return app


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _run(coro):
    return asyncio.run(coro)


def _get(app, url, **kw):
    async def go():
        async with _client(app) as c:
            return await c.get(url, **kw)

    return _run(go())


def _post(app, url, **kw):
    async def go():
        async with _client(app) as c:
            return await c.post(url, **kw)

    return _run(go())


def _patch(app, url, **kw):
    async def go():
        async with _client(app) as c:
            return await c.patch(url, **kw)

    return _run(go())


# ── /info ──────────────────────────────────────────────────────────────────


def test_info_providers(monkeypatch):
    app = _build_app(_FakeCM(), monkeypatch)

    async def go():
        async with _client(app) as c:
            return await c.get("/api/v1/info/providers")

    r = _run(go())
    assert r.status_code == 200
    assert r.json()["providers"] == ["google", "naver", "kakao"]


def test_info_attributions(monkeypatch):
    app = _build_app(_FakeCM(), monkeypatch)

    async def go():
        async with _client(app) as c:
            return await c.get("/api/v1/info/attributions")

    r = _run(go())
    assert r.status_code == 200
    body = r.json()
    assert body["open_source"] == []
    assert body["copyright"] == "© Venezia"
    assert "ai_notice" in body


# ── /user/auth ───────────────────────────────────────────────────────────────


def test_auth_authorize(monkeypatch):
    app = _build_app(_FakeCM(), monkeypatch)
    prov = _FakeProvider()
    monkeypatch.setattr(router_mod, "get_provider", lambda p: prov)
    monkeypatch.setattr(router_mod, "make_state", lambda: "state-abc")

    async def go():
        async with _client(app) as c:
            return await c.get("/api/v1/user/auth/google/authorize")

    r = _run(go())
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "state-abc"
    assert body["authorization_url"] == "https://auth.example/login?state=state-abc"
    assert r.cookies.get("nx_pkce")  # PKCE verifier 쿠키 발급
    # provider 에 S256 code_challenge 가 실제 전달됐는지 (PKCE 불변식) — 비어있지 않아야.
    authz = next(c for c in prov.calls if c[0] == "authz")
    assert authz[1] == "state-abc" and authz[2]  # (state, code_challenge) — challenge 존재


def _set_cookies(r) -> list[str]:
    """응답의 raw Set-Cookie 문자열(소문자) 리스트 — 보안 속성 검증용."""
    return [c.lower() for c in r.headers.get_list("set-cookie")]


def _raw_cookie(cookies: list[str], name: str) -> str:
    """name= 으로 시작하는 raw set-cookie 한 줄 (없으면 '')."""
    return next((c for c in cookies if c.startswith(f"{name.lower()}=")), "")


def test_auth_callback_sets_cookies_and_redirects(monkeypatch):
    from src.config import settings as _s

    monkeypatch.setattr(_s, "JWT_SECRET_KEY", "cb-secret")
    cm = _FakeCM()
    app = _build_app(cm, monkeypatch)
    prov = _FakeProvider()
    monkeypatch.setattr(router_mod, "get_provider", lambda p: prov)
    monkeypatch.setattr(router_mod, "verify_state", lambda state: None)
    monkeypatch.setattr(router_mod, "verify_pkce", lambda signed, state: "verifier-x")

    async def _resolve(cm_arg, provider, provider_sub):
        assert provider == "google" and provider_sub == "psub-9"
        return "minted-uid"

    monkeypatch.setattr(router_mod, "resolve_or_mint_user_id", _resolve)

    async def go():
        async with _client(app) as c:
            return await c.get(
                "/api/v1/user/auth/google/callback",
                params={"code": "c-1", "state": "state-abc"},
                cookies={"nx_pkce": "signed-pkce"},
            )

    r = _run(go())
    assert r.status_code == 302
    assert r.headers["location"] == _s.SPA_COMPLETE_ROUTE
    assert r.cookies.get("nx_access") and r.cookies.get("nx_refresh")
    # 보안 속성 — access=HttpOnly·SameSite=Lax·Path=/api/v1, refresh=HttpOnly·SameSite=Strict·Path 한정.
    scs = _set_cookies(r)
    acc, ref = _raw_cookie(scs, "nx_access"), _raw_cookie(scs, "nx_refresh")
    assert "httponly" in acc and "samesite=lax" in acc and "path=/api/v1" in acc
    assert "secure" in acc  # COOKIE_SECURE default True
    assert "httponly" in ref and "samesite=strict" in ref and "path=/api/v1/user/auth" in ref
    # nx_pkce 1회 consume — 콜백이 삭제(빈 값/max-age=0)
    assert _raw_cookie(scs, "nx_pkce")
    # 콜백이 새 refresh family 생성(put_refresh_family)
    assert any(p[0] == "rf_put" and p[1] == "minted-uid" for p in cm.patches)


def test_auth_connect_ok(monkeypatch):
    cm = _FakeCM()
    app = _build_app(cm, monkeypatch)
    prov = _FakeProvider()
    monkeypatch.setattr(router_mod, "get_provider", lambda p: prov)
    linked: list[tuple] = []

    async def _link(cm_arg, uid, provider, provider_sub):
        linked.append((uid, provider, provider_sub))

    monkeypatch.setattr(router_mod, "link_provider", _link)
    monkeypatch.setattr(router_mod, "verify_state", lambda state: None)
    monkeypatch.setattr(router_mod, "verify_pkce", lambda signed, state: "verifier-c")

    async def go():
        async with _client(app) as c:
            return await c.post(
                "/api/v1/user/auth/naver/connect",
                json={"code": "code-2", "state": "st-c"},
                cookies={"nx_pkce": "signed"},
            )

    r = _run(go())
    assert r.status_code == 200
    assert r.json() == {"user_id": _UID, "connected": "naver"}
    assert linked == [(_UID, "naver", "psub-9")]


def test_auth_connect_missing_code_422(monkeypatch):
    # B1: ConnectRequest 가 code/state required → 누락 본문은 모델단 422
    app = _build_app(_FakeCM(), monkeypatch)
    prov = _FakeProvider()
    monkeypatch.setattr(router_mod, "get_provider", lambda p: prov)

    async def go():
        async with _client(app) as c:
            return await c.post("/api/v1/user/auth/naver/connect", json={})

    r = _run(go())
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_failed"


def test_auth_connect_missing_pkce_422(monkeypatch):
    # code/state 는 있으나 nx_pkce 쿠키 없음 → handler 가 422 (missing PKCE)
    app = _build_app(_FakeCM(), monkeypatch)
    monkeypatch.setattr(router_mod, "get_provider", lambda p: _FakeProvider())

    async def go():
        async with _client(app) as c:
            return await c.post(
                "/api/v1/user/auth/naver/connect", json={"code": "c", "state": "s"}
            )

    r = _run(go())
    assert r.status_code == 422


def test_auth_connect_empty_code_422(monkeypatch):
    # 빈 문자열 code 는 모델(required str) 통과하나 핸들러가 명시 거부 → OAuth 교환 도달 방지
    app = _build_app(_FakeCM(), monkeypatch)
    monkeypatch.setattr(router_mod, "get_provider", lambda p: _FakeProvider())

    async def go():
        async with _client(app) as c:
            return await c.post(
                "/api/v1/user/auth/naver/connect", json={"code": "", "state": "s"}
            )

    r = _run(go())
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_failed"


def test_auth_refresh_rotates_204(monkeypatch):
    import jwt  # noqa: PLC0415

    from src.config import settings as _s

    monkeypatch.setattr(_s, "JWT_SECRET_KEY", "rf-secret")
    cm = _FakeCM(rotate_result="rotated")
    app = _build_app(cm, monkeypatch)
    refresh = router_mod.create_refresh_token("u-9", "fam", "jti-old")

    async def go():
        async with _client(app) as c:
            return await c.post("/api/v1/user/auth/refresh", cookies={"nx_refresh": refresh})

    r = _run(go())
    assert r.status_code == 204
    assert r.cookies.get("nx_access") and r.cookies.get("nx_refresh")
    # 회전은 옛 jti 로 CAS 호출 + 새 refresh 쿠키는 **새** jti 를 실어야 함 (회전 불변식).
    rot = next(p for p in cm.patches if p[0] == "rf_rotate")
    assert rot[1:4] == ("u-9", "fam", "jti-old")
    new_jti = rot[4]
    assert new_jti != "jti-old"
    claims = jwt.decode(r.cookies["nx_refresh"], "rf-secret", algorithms=["HS256"])  # nosemgrep
    assert claims["jti"] == new_jti and claims["typ"] == "refresh"


def test_auth_refresh_concurrent_204_keeps_cookie(monkeypatch):
    from src.config import settings as _s

    monkeypatch.setattr(_s, "JWT_SECRET_KEY", "rf-secret")
    cm = _FakeCM(rotate_result="concurrent")
    app = _build_app(cm, monkeypatch)
    refresh = router_mod.create_refresh_token("u-9", "fam", "jti-prev")

    async def go():
        async with _client(app) as c:
            return await c.post("/api/v1/user/auth/refresh", cookies={"nx_refresh": refresh})

    r = _run(go())
    assert r.status_code == 204
    # 동시 갱신 — 새 토큰 발급 안 함(현 쿠키 유지) → Set-Cookie 없음
    assert _set_cookies(r) == []


def test_auth_refresh_reuse_401_clears_cookies(monkeypatch):
    from src.config import settings as _s

    monkeypatch.setattr(_s, "JWT_SECRET_KEY", "rf-secret")
    cm = _FakeCM(rotate_result="reuse")
    app = _build_app(cm, monkeypatch)
    refresh = router_mod.create_refresh_token("u-9", "fam", "jti-old")

    async def go():
        async with _client(app) as c:
            return await c.post("/api/v1/user/auth/refresh", cookies={"nx_refresh": refresh})

    r = _run(go())
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"
    # 거부 = 죽은 세션 정리 → access/refresh 쿠키 clear (max-age=0/빈 값)
    scs = _set_cookies(r)
    assert _raw_cookie(scs, "nx_access") and _raw_cookie(scs, "nx_refresh")


def test_auth_refresh_no_cookie_401(monkeypatch):
    app = _build_app(_FakeCM(), monkeypatch)

    async def go():
        async with _client(app) as c:
            return await c.post("/api/v1/user/auth/refresh")

    r = _run(go())
    assert r.status_code == 401


def test_auth_logout_revokes_204(monkeypatch):
    from src.config import settings as _s

    monkeypatch.setattr(_s, "JWT_SECRET_KEY", "lo-secret")
    cm = _FakeCM()
    app = _build_app(cm, monkeypatch)
    refresh = router_mod.create_refresh_token("u-9", "fam", "jti")

    async def go():
        async with _client(app) as c:
            return await c.post("/api/v1/user/auth/logout", cookies={"nx_refresh": refresh})

    r = _run(go())
    assert r.status_code == 204
    assert ("rf_revoke", "u-9", "fam") in cm.patches
    # logout = 쿠키 clear
    scs = _set_cookies(r)
    assert _raw_cookie(scs, "nx_access") and _raw_cookie(scs, "nx_refresh")


def test_auth_logout_no_cookie_idempotent_204(monkeypatch):
    app = _build_app(_FakeCM(), monkeypatch)

    async def go():
        async with _client(app) as c:
            return await c.post("/api/v1/user/auth/logout")

    r = _run(go())
    assert r.status_code == 204


def test_auth_logout_cm_failure_still_204_clears(monkeypatch):
    # CM revoke 가 httpx/네트워크 예외(비-HTTPException) → logout 은 여전히 멱등 204 + 쿠키 clear.
    from src.config import settings as _s

    monkeypatch.setattr(_s, "JWT_SECRET_KEY", "lo-secret")
    cm = _FakeCM()

    async def _boom(user_id, family_id):
        raise RuntimeError("cm down")

    cm.revoke_refresh_family = _boom
    app = _build_app(cm, monkeypatch)
    refresh = router_mod.create_refresh_token("u-9", "fam", "jti")

    async def go():
        async with _client(app) as c:
            return await c.post("/api/v1/user/auth/logout", cookies={"nx_refresh": refresh})

    r = _run(go())
    assert r.status_code == 204
    scs = _set_cookies(r)
    assert _raw_cookie(scs, "nx_access") and _raw_cookie(scs, "nx_refresh")


def test_auth_refresh_invalid_token_401(monkeypatch):
    # 위조/만료 refresh 쿠키 → decode_token HTTPException → _auth_reject(401 + clear).
    from src.config import settings as _s

    monkeypatch.setattr(_s, "JWT_SECRET_KEY", "rf-secret")
    app = _build_app(_FakeCM(), monkeypatch)

    async def go():
        async with _client(app) as c:
            return await c.post("/api/v1/user/auth/refresh", cookies={"nx_refresh": "not-a-jwt"})

    r = _run(go())
    assert r.status_code == 401
    scs = _set_cookies(r)
    assert _raw_cookie(scs, "nx_access") and _raw_cookie(scs, "nx_refresh")


def test_auth_refresh_malformed_claims_401(monkeypatch):
    # typ=refresh 이나 fid/jti 결손 → malformed → 401 + clear (회전 미시도).
    import jwt  # noqa: PLC0415

    from src.config import settings as _s

    monkeypatch.setattr(_s, "JWT_SECRET_KEY", "rf-secret")
    cm = _FakeCM()
    app = _build_app(cm, monkeypatch)
    token = jwt.encode(  # nosemgrep
        {"sub": "u-9", "typ": "refresh"}, "rf-secret", algorithm="HS256"
    )

    async def go():
        async with _client(app) as c:
            return await c.post("/api/v1/user/auth/refresh", cookies={"nx_refresh": token})

    r = _run(go())
    assert r.status_code == 401
    assert not any(p[0] == "rf_rotate" for p in cm.patches)  # 회전 미호출


def test_auth_disconnect(monkeypatch):
    app = _build_app(_FakeCM(), monkeypatch)
    unlinked: list[tuple] = []

    async def _unlink(cm_arg, uid, provider):
        unlinked.append((uid, provider))

    monkeypatch.setattr(router_mod, "unlink_provider", _unlink)

    async def go():
        async with _client(app) as c:
            return await c.delete("/api/v1/user/auth/kakao")

    r = _run(go())
    assert r.status_code == 204  # D5 멱등 — 무본문
    assert r.content == b""
    assert unlinked == [(_UID, "kakao")]


# ── /user/account ──────────────────────────────────────────────────────────


def test_account_info_with_profile(monkeypatch):
    # nickname 존재 + providers 존재 → alias=nickname, providers 추출
    cm = _FakeCM(
        profile={
            "nickname": "코코",
            "providers": [{"provider": "google"}, {"provider": "naver"}],
        }
    )
    app = _build_app(cm, monkeypatch)

    async def go():
        async with _client(app) as c:
            return await c.get("/api/v1/user/account")

    r = _run(go())
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == _UID
    assert body["alias"] == "코코"
    assert body["providers"] == ["google", "naver"]


def test_account_info_no_profile_fallback(monkeypatch):
    # profile None → {} → alias fallback 발명가-{uid[:6]}, providers []
    cm = _FakeCM(profile=None)
    app = _build_app(cm, monkeypatch, user={"user_id": "abcdef1234"})

    async def go():
        async with _client(app) as c:
            return await c.get("/api/v1/user/account")

    r = _run(go())
    assert r.status_code == 200
    body = r.json()
    assert body["alias"] == "발명가-abcdef"
    assert body["providers"] == []


def test_get_alias(monkeypatch):
    cm = _FakeCM(profile={"nickname": "냐옹", "updated_at": "ts1"})
    app = _build_app(cm, monkeypatch)

    async def go():
        async with _client(app) as c:
            return await c.get("/api/v1/user/account/alias")

    r = _run(go())
    assert r.status_code == 200
    body = r.json()
    assert body == {"alias": "냐옹"}
    assert r.headers["etag"] == '"ts1"'  # D7 — profile.updated_at


def test_get_alias_no_profile_fallback(monkeypatch):
    # profile 없음 → fallback alias, updated_at 없음 → ETag 없음 (_set_etag no-op)
    cm = _FakeCM()
    app = _build_app(cm, monkeypatch)

    async def go():
        async with _client(app) as c:
            return await c.get("/api/v1/user/account/alias")

    r = _run(go())
    assert r.status_code == 200
    assert r.json()["alias"].startswith("발명가-")
    assert "etag" not in r.headers


def test_set_alias_no_if_match_428(monkeypatch):
    # A-10: If-Match 필수 — 무헤더 → 428(precondition required), write 안 함
    cm = _FakeCM()
    app = _build_app(cm, monkeypatch)

    async def go():
        async with _client(app) as c:
            return await c.put("/api/v1/user/account/alias", json={"alias": "새이름"})

    r = _run(go())
    assert r.status_code == 428
    assert r.json()["error"]["code"] == "precondition_required"
    assert cm.patches == []  # 거부 → write 없음


def test_set_alias_if_match_ok(monkeypatch):
    # If-Match 가 현재 profile.updated_at 과 일치 → 통과 (200)
    cm = _FakeCM(profile={"nickname": "old", "updated_at": "ts1"})
    app = _build_app(cm, monkeypatch)

    async def go():
        async with _client(app) as c:
            return await c.put(
                "/api/v1/user/account/alias",
                json={"alias": "새이름"},
                headers={"If-Match": '"ts1"'},
            )

    r = _run(go())
    assert r.status_code == 200
    assert r.json() == {"alias": "새이름"}
    assert r.headers["etag"] == '"ts-after"'  # 새 버전 ETag
    assert cm.patches == [
        ("profile", _UID, [{"op": "add", "path": "/nickname", "value": "새이름"}])
    ]


def test_set_alias_if_match_mismatch_412(monkeypatch):
    # If-Match 가 현재 profile.updated_at 과 불일치 → 412 (낙관적 동시성, D7)
    cm = _FakeCM(profile={"nickname": "old", "updated_at": "ts1"})
    app = _build_app(cm, monkeypatch)

    async def go():
        async with _client(app) as c:
            return await c.put(
                "/api/v1/user/account/alias",
                json={"alias": "새이름"},
                headers={"If-Match": '"STALE"'},
            )

    r = _run(go())
    assert r.status_code == 412
    assert r.json()["error"]["code"] == "conflict"
    assert cm.patches == []  # 불일치 → patch 안 함


def test_set_alias_empty_422(monkeypatch):
    cm = _FakeCM()
    app = _build_app(cm, monkeypatch)

    async def go():
        async with _client(app) as c:
            return await c.put("/api/v1/user/account/alias", json={"alias": "   "})

    r = _run(go())
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_failed"
    assert cm.patches == []


# ── _progress (직접 호출로 전 분기) ──────────────────────────────────────────


def test_progress_not_dict():
    assert _progress(None) == {"phase": "discovery"}
    assert _progress("nope") == {"phase": "discovery"}


def test_progress_full_scores_and_overall():
    out = _progress(
        {
            "overall_score": 0.5,
            "scores": {"clarity": 0.1, "completeness": 0.2, "potential": 0.3},
        }
    )
    assert out == {
        "phase": "discovery",
        "progress": 0.5,
        "clarity": 0.1,
        "completeness": 0.2,
        "potential": 0.3,
    }


def test_progress_alt_score_keys_and_no_overall():
    # overall_score 비수치 → None, scores 의 alt 키 fallback 경로
    out = _progress(
        {
            "overall_score": "bad",
            "scores": {
                "clarity": 0.9,
                "completeness": 0.8,
                "potential": 0.7,
            },
        }
    )
    assert out["progress"] is None
    assert out["clarity"] == 0.9
    assert out["completeness"] == 0.8
    assert out["potential"] == 0.7


def test_progress_scores_not_dict():
    # scores 가 dict 가 아니면 {} 로 대체 → 모든 지표 None, overall int 경로
    out = _progress({"overall_score": 1, "scores": ["x"]})
    assert out["progress"] == 1.0
    assert out["clarity"] is None
    assert out["completeness"] is None
    assert out["potential"] is None


# ── /user/works ──────────────────────────────────────────────────────────────


def test_works_new(monkeypatch):
    cm = _FakeCM(session={"work_id": "w-new", "created_at": "2026-06-04T00:00:00Z"})
    app = _build_app(cm, monkeypatch)

    async def go():
        async with _client(app) as c:
            return await c.post("/api/v1/user/works")

    r = _run(go())
    assert r.status_code == 201
    body = r.json()
    assert body == {"work_id": "w-new", "created_at": "2026-06-04T00:00:00Z"}
    assert r.headers["location"] == "/api/v1/works/w-new"  # 201 + Location (생성 자원)


def test_works_new_no_work_id_500(monkeypatch):
    # CM 이 work_id 미반환 → 위치 없는 201 금지(계약 구멍) → 500 internal (Location 가드)
    cm = _FakeCM(session={"created_at": "2026-06-04T00:00:00Z"})
    app = _build_app(cm, monkeypatch)

    async def go():
        async with _client(app) as c:
            return await c.post("/api/v1/user/works")

    r = _run(go())
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "internal"


def test_works_new_idempotency_replay(monkeypatch):
    # 같은 Idempotency-Key 재시도 → 같은 work_id + Location 재생, create_session 1회만 (D6)
    cm = _FakeCM(session={"work_id": "w-new", "created_at": "2026-06-04T00:00:00Z"})
    app = _build_app(cm, monkeypatch)
    hdr = {"Idempotency-Key": "abc-123"}

    async def go():
        async with _client(app) as c:
            r1 = await c.post("/api/v1/user/works", headers=hdr)
            r2 = await c.post("/api/v1/user/works", headers=hdr)
            return r1, r2

    r1, r2 = _run(go())
    assert r1.status_code == r2.status_code == 201
    assert r1.json() == r2.json()  # 멱등 재생 동일
    assert r1.json() == {"work_id": "w-new", "created_at": "2026-06-04T00:00:00Z"}
    assert r1.headers["location"] == r2.headers["location"] == "/api/v1/works/w-new"
    assert cm.session_calls == 1  # 2번째는 replay — 재생성 안 함
    assert (_UID, "works:abc-123") in cm._idem  # 연산별 스코프 키 (교차 엔드포인트 collision 방지)


def test_works_new_idempotency_busy_409(monkeypatch):
    # 동일 키를 다른 요청이 처리 중(미완료 선점) → 409, 처리 안 함
    cm = _FakeCM(session={"work_id": "w", "created_at": "t"})
    cm._idem[(_UID, "works:busy-k")] = {"claimed_at": "x"}  # in-flight 선점 존재
    app = _build_app(cm, monkeypatch)

    async def go():
        async with _client(app) as c:
            return await c.post("/api/v1/user/works", headers={"Idempotency-Key": "busy-k"})

    r = _run(go())
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "conflict"
    assert cm.session_calls == 0


def test_works_new_idempotency_release_on_failure(monkeypatch):
    # 부수효과 실패(work_id 미반환 → 500) → 선점 해제(재시도 즉시 재선점 가능)
    cm = _FakeCM(session={"created_at": "t"})  # work_id 없음
    app = _build_app(cm, monkeypatch)

    async def go():
        async with _client(app) as c:
            return await c.post("/api/v1/user/works", headers={"Idempotency-Key": "fail-k"})

    r = _run(go())
    assert r.status_code == 500
    assert (_UID, "works:fail-k") not in cm._idem  # 선점 해제됨


def test_works_brief(monkeypatch):
    # 3 raw item: 정상(w-a), skip(work_id 없음), except(w-bad → manifest raise)
    cm = _FakeCM(
        sessions={
            "inventions": [
                {"work_id": "w-a", "created_at": "2026-01-01T00:00:00Z"},
                {"no_id": True},  # dict 이나 work_id 없음 → skip
                "not-a-dict",  # dict 아님 → skip
                {"work_id": "w-bad"},  # except 분기
            ]
        },
        manifests={
            "w-a": {
                "title": "제목 A",
                "last_activity_at": "2026-02-02T00:00:00Z",
                "created_at": "2026-01-01T00:00:00Z",
            },
        },
        maturity={"overall_score": 0.4, "scores": {"clarity": 0.4}},
    )
    cm.manifest_raise_for = {"w-bad"}
    app = _build_app(cm, monkeypatch)

    async def go():
        async with _client(app) as c:
            return await c.get("/api/v1/user/works")

    r = _run(go())
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["work_id"] == "w-a"
    assert items[0]["title"] == "제목 A"
    assert items[0]["progress"]["progress"] == 0.4


def test_works_brief_title_fallback_and_maturity_none(monkeypatch):
    # manifest title 없음 → fallback 발명 {wid[:8]}, last_activity 없음 → updated_at,
    # created_at 없음 → raw_item.created_at, maturity None → _progress(None)
    cm = _FakeCM(
        sessions={"inventions": [{"work_id": "abcdefghij", "created_at": "2026-03-03"}]},
        manifests={"abcdefghij": {"updated_at": "2026-04-04"}},
        maturity=None,
    )
    app = _build_app(cm, monkeypatch)

    async def go():
        async with _client(app) as c:
            return await c.get("/api/v1/user/works")

    r = _run(go())
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    it = items[0]
    assert it["title"] == "발명 abcdefgh"
    # B11: timestamp 가 datetime 으로 정규화(date-only → ...T00:00:00) — 계약이 typed datetime
    assert it["last_activity_at"] == "2026-04-04T00:00:00"
    assert it["created_at"] == "2026-03-03T00:00:00"
    # WorkMaturitySnapshot 모델이 optional 필드를 None 으로 채워 직렬화 (maturity None 경로)
    assert it["progress"] == {
        "phase": "discovery",
        "progress": None,
        "clarity": None,
        "completeness": None,
        "potential": None,
    }


def test_works_brief_empty_sessions(monkeypatch):
    # list_sessions None → {} → inventions 없음 → 빈 items
    cm = _FakeCM(sessions=None)
    app = _build_app(cm, monkeypatch)

    async def go():
        async with _client(app) as c:
            return await c.get("/api/v1/user/works")

    r = _run(go())
    assert r.status_code == 200
    assert r.json()["items"] == []


# ── /works/{work_id} 진입점 (가벼운 식별 {work_id,title}, A-9 — 탐색 링크 없음) ──


def test_work_entry_index(monkeypatch):
    cm = _FakeCM(manifest={"title": "내 발명"})
    app = _build_app(cm, monkeypatch)

    async def go():
        async with _client(app) as c:
            return await c.get("/api/v1/works/w-z")

    r = _run(go())
    assert r.status_code == 200
    body = r.json()
    # A-9: 진입점은 가벼운 식별만 — 탐색 링크(_links) 없음. 하위 자원은 고정 URL 템플릿.
    assert body == {"work_id": "w-z", "title": "내 발명"}


def test_work_entry_404(monkeypatch):
    cm = _FakeCM(manifest=None)
    app = _build_app(cm, monkeypatch)

    async def go():
        async with _client(app) as c:
            return await c.get("/api/v1/works/missing")

    r = _run(go())
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "work_not_found"


# ── /works/{work_id}/meta ────────────────────────────────────────────────────


def test_work_info_detail_ok(monkeypatch):
    cm = _FakeCM(
        manifest={
            "title": "내 발명",
            "title_source": "user",
            "last_activity_at": "2026-05-05",
            "created_at": "2026-01-01",
            "updated_at": "2026-05-05",
        },
        maturity={"overall_score": 0.6, "scores": {"clarity": 0.6}},
    )
    app = _build_app(cm, monkeypatch)

    async def go():
        async with _client(app) as c:
            return await c.get("/api/v1/works/w-x/meta")

    r = _run(go())
    assert r.status_code == 200
    body = r.json()
    assert body["work_id"] == "w-x"
    assert body["title"] == "내 발명"
    assert body["title_source"] == "user"
    assert body["progress"]["progress"] == 0.6
    assert r.headers["etag"] == '"2026-05-05"'  # D7 — manifest.updated_at


def test_work_info_detail_fallbacks(monkeypatch):
    # title/title_source 없음 → fallback, maturity None
    cm = _FakeCM(manifest={"updated_at": "2026-05-05"}, maturity=None)
    app = _build_app(cm, monkeypatch)

    async def go():
        async with _client(app) as c:
            return await c.get("/api/v1/works/abcdefghxyz/meta")

    r = _run(go())
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "발명 abcdefgh"
    assert body["title_source"] == "auto"
    assert body["last_activity_at"] == "2026-05-05T00:00:00"  # B11: datetime 정규화
    assert body["created_at"] is None
    # WorkMaturitySnapshot 모델이 optional 필드를 None 으로 채워 직렬화 (maturity None 경로)
    assert body["progress"] == {
        "phase": "discovery",
        "progress": None,
        "clarity": None,
        "completeness": None,
        "potential": None,
    }


def test_work_info_detail_404(monkeypatch):
    cm = _FakeCM(manifest=None)
    app = _build_app(cm, monkeypatch)

    async def go():
        async with _client(app) as c:
            return await c.get("/api/v1/works/missing/meta")

    r = _run(go())
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "work_not_found"


def test_work_info_rename_no_if_match_428(monkeypatch):
    # A-10: If-Match 필수 — 무헤더 → 428(precondition required), patch 안 함
    cm = _FakeCM(manifest={"title": "x", "updated_at": "2026-06-04"}, maturity=None)
    app = _build_app(cm, monkeypatch)

    async def go():
        async with _client(app) as c:
            return await c.patch("/api/v1/works/w-y/meta", json={"title": "새 제목"})

    r = _run(go())
    assert r.status_code == 428
    assert r.json()["error"]["code"] == "precondition_required"
    assert cm.patches == []  # 거부 → patch 없음


def test_work_info_rename_if_match_ok(monkeypatch):
    # If-Match 가 현재 manifest.updated_at 과 일치 → 통과
    cm = _FakeCM(
        manifest={"title": "x", "title_source": "user", "updated_at": "2026-06-04"},
        maturity=None,
    )
    app = _build_app(cm, monkeypatch)

    async def go():
        async with _client(app) as c:
            return await c.patch(
                "/api/v1/works/w-y/meta",
                json={"title": "새 제목"},
                headers={"If-Match": '"2026-06-04"'},
            )

    r = _run(go())
    assert r.status_code == 200
    assert len(cm.patches) == 1
    kind, uid, wid, ops = cm.patches[0]
    assert kind == "manifest" and uid == _UID and wid == "w-y"
    assert [op["path"] for op in ops] == ["/title", "/title_source", "/updated_at"]
    assert ops[0]["value"] == "새 제목" and ops[1]["value"] == "user"


def test_work_info_rename_if_match_mismatch_412(monkeypatch):
    # If-Match 가 현재 manifest.updated_at 과 불일치 → 412, patch 안 함 (D7)
    cm = _FakeCM(manifest={"title": "x", "updated_at": "2026-06-04"}, maturity=None)
    app = _build_app(cm, monkeypatch)

    async def go():
        async with _client(app) as c:
            return await c.patch(
                "/api/v1/works/w-y/meta",
                json={"title": "새 제목"},
                headers={"If-Match": '"STALE"'},
            )

    r = _run(go())
    assert r.status_code == 412
    assert r.json()["error"]["code"] == "conflict"
    assert cm.patches == []


def test_work_info_rename_404(monkeypatch):
    # manifest 없음 → 404 (If-Match 검사 전)
    cm = _FakeCM(manifest=None)
    app = _build_app(cm, monkeypatch)

    async def go():
        async with _client(app) as c:
            return await c.patch("/api/v1/works/missing/meta", json={"title": "새 제목"})

    r = _run(go())
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "work_not_found"
    assert cm.patches == []


def test_work_info_rename_empty_422(monkeypatch):
    cm = _FakeCM()
    app = _build_app(cm, monkeypatch)

    async def go():
        async with _client(app) as c:
            return await c.patch("/api/v1/works/w-y/meta", json={"title": "   "})

    r = _run(go())
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_failed"
    assert cm.patches == []


# ===========================================================================
# works/{id} chain-surface reads (이관 ← DRO sub-plan ①): phase / thread.messages / estimate read
# ===========================================================================


# ── phase/current ──────────────────────────────────────────────────────────


def test_phase_current_manifest_missing_404(monkeypatch):
    app = _build_app(_FakeCM(manifest=None), monkeypatch)
    r = _get(app, f"/api/v1/works/{_WORK}/phase")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "work_not_found"


def test_phase_current_drafting_with_doc_is_complete(monkeypatch):
    cm = _FakeCM(manifest={"current_phase": "drafting"}, doc_body=b"docx")
    r = _get(_build_app(cm, monkeypatch), f"/api/v1/works/{_WORK}/phase")
    assert r.status_code == 200
    assert r.json() == {"state": "complete"}


def test_phase_current_drafting_no_doc_is_drafting(monkeypatch):
    cm = _FakeCM(manifest={"current_phase": "drafting"}, doc_body=None)
    r = _get(_build_app(cm, monkeypatch), f"/api/v1/works/{_WORK}/phase")
    assert r.json() == {"state": "drafting"}


def test_phase_current_ready_when_maturity_over_threshold(monkeypatch):
    cm = _FakeCM(manifest={"current_phase": "discovery"}, maturity={"overall_score": 0.8})
    r = _get(_build_app(cm, monkeypatch), f"/api/v1/works/{_WORK}/phase")
    assert r.json() == {"state": "ready"}


def test_phase_current_discovery_when_low_or_missing(monkeypatch):
    cm = _FakeCM(manifest={}, maturity={"overall_score": None})
    r = _get(_build_app(cm, monkeypatch), f"/api/v1/works/{_WORK}/phase")
    assert r.json() == {"state": "discovery"}


# ── phase/transition ────────────────────────────────────────────────────────


def test_phase_transition_manifest_missing_404(monkeypatch):
    app = _build_app(_FakeCM(manifest=None), monkeypatch)
    r = _patch(app, f"/api/v1/works/{_WORK}/phase")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "work_not_found"


def test_phase_transition_discovery_to_drafting(monkeypatch):
    cm = _FakeCM(manifest={"current_phase": "discovery"})
    r = _patch(_build_app(cm, monkeypatch), f"/api/v1/works/{_WORK}/phase")
    assert r.json() == {"state": "drafting"}
    assert cm.patches and len(cm.patches[0][3]) == 2
    assert cm.patches[0][3][0]["value"] == "drafting"


def test_phase_transition_non_discovery_unchanged(monkeypatch):
    cm = _FakeCM(manifest={"current_phase": "drafting"})
    r = _patch(_build_app(cm, monkeypatch), f"/api/v1/works/{_WORK}/phase")
    assert r.json() == {"state": "drafting"}
    assert cm.patches[0][3][0]["value"] == "drafting"


# ── thread/messages ──────────────────────────────────────────────────────────


def _msg(role="user", content="hi"):
    return {"role": role, "content": content, "timestamp": "2026-06-04T00:00:00Z"}


def test_thread_messages_returns_page_no_cursor(monkeypatch):
    conv = {"messages": [_msg(content=str(i)) for i in range(3)]}
    r = _get(
        _build_app(_FakeCM(conversation=conv), monkeypatch),
        f"/api/v1/works/{_WORK}/thread/messages",
    )
    body = r.json()
    assert len(body["items"]) == 3
    assert body["next_cursor"] is None


def test_thread_messages_limit_sets_next_cursor(monkeypatch):
    conv = {"messages": [_msg(content=str(i)) for i in range(5)]}
    r = _get(
        _build_app(_FakeCM(conversation=conv), monkeypatch),
        f"/api/v1/works/{_WORK}/thread/messages",
        params={"limit": 2},
    )
    body = r.json()
    assert len(body["items"]) == 2
    assert body["items"][0]["content"] == "3"
    assert body["next_cursor"] == "3"


def test_thread_messages_before_cursor_slices(monkeypatch):
    conv = {"messages": [_msg(content=str(i)) for i in range(5)]}
    r = _get(
        _build_app(_FakeCM(conversation=conv), monkeypatch),
        f"/api/v1/works/{_WORK}/thread/messages",
        params={"before": "3"},
    )
    assert [m["content"] for m in r.json()["items"]] == ["0", "1", "2"]
    assert r.json()["next_cursor"] is None


def test_thread_messages_none_conversation_empty(monkeypatch):
    r = _get(
        _build_app(_FakeCM(conversation=None), monkeypatch),
        f"/api/v1/works/{_WORK}/thread/messages",
    )
    assert r.json() == {"items": [], "next_cursor": None}


def test_thread_messages_non_dict_conversation_empty(monkeypatch):
    r = _get(
        _build_app(_FakeCM(conversation=["not", "a", "dict"]), monkeypatch),
        f"/api/v1/works/{_WORK}/thread/messages",
    )
    assert r.json()["items"] == []


# ── estimate/roadmap pull ──────────────────────────────────────────────────────


def _roadmap_item(item_id="r1"):
    return {
        "id": item_id,
        "title": "T",
        "description": "D",
        "status": "pending",
        "priority": 1,
        "input_type": "chat",
    }


def test_roadmap_pull_list(monkeypatch):
    r = _get(
        _build_app(_FakeCM(roadmap=[_roadmap_item()]), monkeypatch),
        f"/api/v1/works/{_WORK}/estimate/roadmap",
    )
    assert len(r.json()["items"]) == 1


def test_roadmap_pull_non_list_empty(monkeypatch):
    r = _get(
        _build_app(_FakeCM(roadmap={"not": "list"}), monkeypatch),
        f"/api/v1/works/{_WORK}/estimate/roadmap",
    )
    assert r.json()["items"] == []


# ── estimate/maturity ──────────────────────────────────────────────────────────


def test_estimate_maturity_dict_passthrough(monkeypatch):
    cm = _FakeCM(maturity={"overall_score": 0.5, "scores": {}})
    r = _get(_build_app(cm, monkeypatch), f"/api/v1/works/{_WORK}/estimate/maturity")
    assert r.json()["overall_score"] == 0.5


def test_estimate_maturity_shaped_null_when_uncomputed(monkeypatch):
    r = _get(
        _build_app(_FakeCM(maturity=None), monkeypatch), f"/api/v1/works/{_WORK}/estimate/maturity"
    )
    body = r.json()
    assert body["overall_score"] is None
    assert body["scores"] == {"clarity": None, "completeness": None, "potential": None}
