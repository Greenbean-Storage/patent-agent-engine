"""100.Nexus REST endpoints — info + user(auth/account/works ops) + works/{id} 자원.

트리 (스코프: 전역 info / 사용자 user / work works) — RESTful 정규화(C1):
  /api/v1/info/{providers,attributions}
  /api/v1/user/auth/{provider}/{authorize,callback,connect(POST),disconnect(DELETE)}
  /api/v1/user/account(GET) · /api/v1/user/account/alias(GET·PUT)
  /api/v1/user/works(POST 생성·GET 목록)
  /api/v1/works/{work_id}/meta(GET·PATCH) · phase(GET·PATCH) · thread/messages
  /api/v1/works/{work_id}/estimate/{roadmap(GET)·roadmap/{item_id}(PATCH)·maturity}
  /api/v1/works/{work_id}/media(POST·GET) · media/{media_id}(GET·DELETE)
  /api/v1/works/{work_id}/output/draft(POST·GET) · output/draft/preview(GET)

설계 철칙: user_id ⊥ JWT ⊥ provider sub. user_id 는 서버가 결정(JWT 추출 or OPEN 고정).
work_id = 세션/작업 식별자 (외부·내부 단일 명칭).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import venezia_media_config
from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    Header,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import JSONResponse, RedirectResponse, Response
from venezia_contracts.models.dro_api.account_api import (
    AccountInfoResponse,
    AliasResponse,
    AliasUpdateRequest,
    AttributionsResponse,
    AuthorizeResponse,
    ConnectRequest,
    ConnectResponse,
    MetaRenameRequest,
    ProvidersResponse,
    WorkBriefResponse,
    WorkCreateResponse,
    WorkDetailResponse,
    WorkEntryResponse,
)
from venezia_contracts.models.dro_api.document import DraftBuildResponse, DraftPreviewResponse
from venezia_contracts.models.dro_api.error import ErrorCode, ErrorEnvelope
from venezia_contracts.models.dro_api.roadmap import RoadmapItem, RoadmapSubmitRequest
from venezia_contracts.models.dro_api.upload import (
    MediaUploadUrlRequest,
    PresignUploadResponse,
)
from venezia_contracts.models.dro_api.work_api import (
    EstimateMaturityResponse,
    MediaDownloadResponse,
    MediaListResponse,
    PhaseStateResponse,
    RoadmapPullResponse,
    ThreadMessagesResponse,
)

from . import event_consumer, ws_inbound
from .auth import (
    SUPPORTED_PROVIDERS,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    get_provider,
    link_provider,
    make_pkce,
    make_state,
    resolve_or_mint_user_id,
    sign_pkce,
    unlink_provider,
    user_id_from_token,
    verify_pkce,
    verify_state,
)
from .cm_client import get_cm_client
from .config import settings
from .dro_client import control_output
from .errors import APIError
from .message_flow import handle_message
from .ws_manager import get_production_ws_registry

log = logging.getLogger(__name__)
# 주요 에러를 spec 에 typed 로 노출 (frontend 가 에러도 enum 으로 switch) — D6
def _err(*codes: int) -> dict:
    return {c: {"model": ErrorEnvelope} for c in codes}


# 공통(거의 모든 라우트): 인증 401 · 조회 404 · 검증 400/422 · 서버 500(D1, 모든 라우트 도달).
# 라우트별 추가: 멱등 409 · If-Match stale 412(+428 custom openapi) · placeholder 501.
# (read 는 409/412/501 미선언 — 도달 불가. proposal 501 은 status_code=501 로 표기.)
_ERR_RESPONSES: dict = _err(400, 401, 404, 422, 500)
_ERR_CONFLICT: dict = _err(409)  # 멱등 충돌 (Idempotency-Key 진행중) — POST works/media
_ERR_IF_MATCH: dict = _err(412)  # If-Match stale (428 무헤더는 custom openapi) — alias/meta write
# 생성(201) 응답의 Location 헤더를 openapi 에 노출 — 런타임은 response.headers 로 set (V2)
_LOCATION_201: dict = {
    201: {
        "headers": {"Location": {"description": "생성된 자원 주소", "schema": {"type": "string"}}}
    }
}
# 갱신/조회(200) 응답의 ETag 헤더를 openapi 에 노출 — 런타임은 response.headers 로 set (V3·D7)
_ETAG_200: dict = {
    200: {
        "headers": {
            "ETag": {
                "description": "자원 버전 (updated_at) — If-Match 기준",
                "schema": {"type": "string"},
            }
        }
    }
}
router = APIRouter(responses=_ERR_RESPONSES)


# ── 멱등성(Idempotency-Key) · 동시성(If-Match/ETag) 공통 헬퍼 (C3, V3) ──


async def _idem_begin(
    user_id: str, scope: str, idem_key: str | None, response: Response
) -> tuple[str, dict[str, Any] | None]:
    """IK 처리 시작 (D6, 원자 선점). 반환 (action, body):

    - ('replay', body): 완료 기록 존재 → body+Location 재생 (호출자 즉시 반환).
    - ('busy', None): 동일 키를 다른 요청이 처리 중 → 호출자 409.
    - ('proceed', None): 선점 성공(또는 무키) → 작업 후 _idem_finish, 실패 시 _idem_release.

    scope = 연산 식별(`works`/`media`) — 같은 키를 다른 엔드포인트에 재사용해도 교차 replay 방지.
    """
    if not idem_key:
        return ("proceed", None)
    state, rec = await get_cm_client().claim_idempotency(user_id, f"{scope}:{idem_key}")
    if state == "done":
        rec = rec or {}
        if rec.get("location"):
            response.headers["Location"] = rec["location"]
        return ("replay", rec.get("body"))
    if state == "in_flight":
        return ("busy", None)
    return ("proceed", None)


async def _idem_finish(
    user_id: str, scope: str, idem_key: str | None, body: dict[str, Any], location: str
) -> None:
    """선점한 키를 결과로 확정(done) (D6). 무키 = no-op."""
    if not idem_key:
        return
    await get_cm_client().put_idempotency(
        user_id,
        f"{scope}:{idem_key}",
        {
            "status": 201,
            "body": body,
            "location": location,
            "created_at": datetime.now(UTC).isoformat(),
        },
    )


async def _idem_release(user_id: str, scope: str, idem_key: str | None) -> None:
    """부수효과 실패 시 선점 해제 — 재시도가 TTL 안 기다리고 즉시 재선점 (D6). 무키 = no-op."""
    if not idem_key:
        return
    await get_cm_client().delete_idempotency(user_id, f"{scope}:{idem_key}")


def _set_etag(response: Response, updated_at: Any) -> None:
    """ETag = 자원 updated_at (따옴표) — If-Match 의 버전 기준 (D7)."""
    if updated_at:
        response.headers["ETag"] = f'"{updated_at}"'


def _check_if_match(if_match: str | None, current_updated_at: Any) -> None:
    """If-Match 필수(A-10) — 무헤더 = 428(precondition required), 불일치 = 412(낙관적 동시성)."""
    if if_match is None:
        raise APIError(ErrorCode.precondition_required, 428, "If-Match required")
    if if_match.strip('"') != str(current_updated_at):
        raise APIError(ErrorCode.conflict, 412, "If-Match 불일치 — 자원이 그새 변경됨")


_API = "/api/v1"


def _uid(user: dict) -> str:
    return user["user_id"]


_READY_THRESHOLD = 0.7  # maturity.overall_score ≥ 임계 → ready (튜너블)


# ===========================================================================
# /info — 전역·무인증
# ===========================================================================


@router.get("/api/v1/info/providers", response_model=ProvidersResponse)
async def info_providers() -> dict[str, Any]:
    """가용 로그인 provider 목록 (로그인 UI 용)."""
    return {"providers": list(SUPPORTED_PROVIDERS)}


@router.get("/api/v1/info/attributions", response_model=AttributionsResponse)
async def info_attributions() -> dict[str, Any]:
    """OSS·AI·저작권 고지 (백엔드 의존성/AI 사용)."""
    return {
        "open_source": [],
        "ai_notice": "본 서비스는 결과 생성을 위해 외부 모델을 활용합니다.",
        "copyright": "© Venezia",
    }


# ===========================================================================
# /user/auth — federated 로그인 (3 provider)
# ===========================================================================


# ── 인증 쿠키 헬퍼 (httpOnly access/refresh + PKCE, C1) ──

_AUTH_PATH = f"{_API}/user/auth"


def _set_auth_cookies(response: Response, user_id: str, family_id: str, jti: str) -> None:
    """access(Lax·/api/v1) + refresh(Strict·/api/v1/user/auth) 쿠키 set."""
    response.set_cookie(
        settings.ACCESS_COOKIE_NAME,
        create_access_token(user_id),
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        path=_API,
    )
    response.set_cookie(
        settings.REFRESH_COOKIE_NAME,
        create_refresh_token(user_id, family_id, jti),
        max_age=settings.REFRESH_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="strict",
        path=_AUTH_PATH,
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(settings.ACCESS_COOKIE_NAME, path=_API)
    response.delete_cookie(settings.REFRESH_COOKIE_NAME, path=_AUTH_PATH)


def _auth_reject(message: str) -> JSONResponse:
    """refresh 거부/만료/재사용 → 401 + 무효 쿠키 clear (죽은 세션 깔끔히 종료)."""
    resp = JSONResponse(
        {"error": {"code": ErrorCode.unauthorized.value, "message": message}},
        status_code=401,
    )
    _clear_auth_cookies(resp)
    return resp


async def _issue_new_session(response: Response, user_id: str) -> None:
    """최초 로그인 — 새 refresh family 생성(CM) + access/refresh 쿠키 발급."""
    family_id = str(uuid.uuid4())
    jti = str(uuid.uuid4())
    await get_cm_client().put_refresh_family(user_id, family_id, jti)
    _set_auth_cookies(response, user_id, family_id, jti)


@router.get("/api/v1/user/auth/{provider}/authorize", response_model=AuthorizeResponse)
async def auth_authorize(provider: str, response: Response) -> dict[str, Any]:
    """authorize URL + state + PKCE verifier 를 `nx_pkce` 쿠키로 발급(콜백 consume)."""
    p = get_provider(provider)
    state = make_state()
    verifier, challenge = make_pkce()
    url = await p.authorization_url(state, challenge)
    response.set_cookie(
        settings.PKCE_COOKIE_NAME,
        sign_pkce(verifier, state),
        max_age=600,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        path=_AUTH_PATH,
    )
    return {"authorization_url": url, "state": state}


@router.get("/api/v1/user/auth/{provider}/callback")
async def auth_callback(
    provider: str,
    code: str = Query(...),
    state: str = Query(...),
    nx_pkce: str | None = Cookie(default=None, alias=settings.PKCE_COOKIE_NAME),
) -> Response:
    """provider redirect 착지 — PKCE 검증·토큰 교환 후 httpOnly 쿠키 set + SPA 라우트로 302.

    토큰은 본문으로 노출하지 않음(JS 미접근). user_id 는 이후 서버가 쿠키에서 해석.
    """
    p = get_provider(provider)
    verify_state(state)
    if not nx_pkce:
        raise HTTPException(400, "missing PKCE cookie")
    verifier = verify_pkce(nx_pkce, state)
    provider_sub, _email, _name = await p.exchange(code, verifier)
    cm = get_cm_client()
    user_id = await resolve_or_mint_user_id(cm, provider, provider_sub)
    resp = RedirectResponse(url=settings.SPA_COMPLETE_ROUTE, status_code=302)
    resp.headers["Cache-Control"] = "no-store"
    await _issue_new_session(resp, user_id)
    resp.delete_cookie(settings.PKCE_COOKIE_NAME, path=_AUTH_PATH)
    return resp


@router.post(
    "/api/v1/user/auth/{provider}/connect", status_code=200, response_model=ConnectResponse
)
async def auth_connect(
    provider: str,
    response: Response,
    body: ConnectRequest,
    user: dict = Depends(get_current_user),
    nx_pkce: str | None = Cookie(default=None, alias=settings.PKCE_COOKIE_NAME),
) -> dict[str, Any]:
    """로그인 상태에서 다른 provider code(+state)를 현재 user_id 에 연결 (PKCE)."""
    p = get_provider(provider)
    code, state = body.code, body.state  # 누락 키는 ConnectRequest 가 422
    if not code or not state:  # 빈 문자열은 모델이 안 막음 → 명시 거부(형제 핸들러와 일관)
        raise APIError(ErrorCode.validation_failed, 422, "code & state required")
    if not nx_pkce:
        raise APIError(ErrorCode.validation_failed, 422, "missing PKCE")
    verify_state(state)
    verifier = verify_pkce(nx_pkce, state)
    provider_sub, _e, _n = await p.exchange(code, verifier)
    cm = get_cm_client()
    await link_provider(cm, _uid(user), provider, provider_sub)
    response.delete_cookie(settings.PKCE_COOKIE_NAME, path=_AUTH_PATH)
    return {"user_id": _uid(user), "connected": provider}


@router.delete("/api/v1/user/auth/{provider}", status_code=204)
async def auth_disconnect(provider: str, user: dict = Depends(get_current_user)) -> Response:
    """provider 연결 해제 — 멱등 **204**(미연결이어도 204). unlink_provider 가 no-op 안전."""
    cm = get_cm_client()
    await unlink_provider(cm, _uid(user), provider)
    return Response(status_code=204)


@router.post("/api/v1/user/auth/refresh", status_code=204)
async def auth_refresh(
    nx_refresh: str | None = Cookie(default=None, alias=settings.REFRESH_COOKIE_NAME),
) -> Response:
    """refresh 회전 — refresh 쿠키 검증 + family 회전 → 새 access/refresh 쿠키(204).

    재사용(old jti)·revoked·missing → 서버측 family revoke + 401 + 무효 쿠키 clear(재로그인).
    동시/재시도(직전 jti) → 204(현 쿠키 유지, 이미 다른 요청이 회전 — 오탐 logout 방지).
    """
    if not nx_refresh:
        return _auth_reject("refresh token required")
    try:
        claims = decode_token(nx_refresh, expected_typ="refresh")
    except HTTPException:
        return _auth_reject("invalid or expired refresh")
    user_id, family_id, jti = claims.get("sub"), claims.get("fid"), claims.get("jti")
    if not (user_id and family_id and jti):
        return _auth_reject("malformed refresh")
    new_jti = str(uuid.uuid4())
    result = await get_cm_client().rotate_refresh_family(user_id, family_id, jti, new_jti)
    if result == "rotated":
        resp = Response(status_code=204)
        _set_auth_cookies(resp, user_id, family_id, new_jti)
        return resp
    if result == "concurrent":
        return Response(status_code=204)  # 동시 갱신 — 현 쿠키 유효, 새로 발급 안 함
    return _auth_reject("refresh rejected — re-login required")


@router.post("/api/v1/user/auth/logout", status_code=204)
async def auth_logout(
    nx_refresh: str | None = Cookie(default=None, alias=settings.REFRESH_COOKIE_NAME),
) -> Response:
    """logout — refresh family revoke + 쿠키 clear. 쿠키 없거나 만료여도 멱등 204."""
    if nx_refresh:
        try:
            claims = decode_token(nx_refresh, expected_typ="refresh")
            await get_cm_client().revoke_refresh_family(claims["sub"], claims["fid"])
        except Exception:  # noqa: BLE001 — logout 은 항상 멱등 204 (만료 토큰·CM 장애 무관, best-effort)
            log.warning("auth_logout revoke best-effort 실패", exc_info=True)
    resp = Response(status_code=204)
    _clear_auth_cookies(resp)
    return resp


# ===========================================================================
# /user/account — 프로필 (PII 0, nickname=alias 만)
# ===========================================================================


async def _profile(user_id: str) -> dict[str, Any]:
    cm = get_cm_client()
    prof = await cm.get_profile(user_id) or {}
    return {
        "user_id": user_id,
        "alias": prof.get("nickname") or f"발명가-{user_id[:6]}",
        "providers": [p.get("provider") for p in (prof.get("providers") or [])],
    }


@router.get("/api/v1/user/account", response_model=AccountInfoResponse)
async def account_info(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """내 정보 — user_id, alias, 연결된 provider. (PII 0 — 실명·이메일 없음)."""
    data = await _profile(_uid(user))
    return data


@router.get("/api/v1/user/account/alias", response_model=AliasResponse, responses=_ETAG_200)
async def get_alias(response: Response, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """별명 조회 — ETag(profile.updated_at) 동반 (PUT 의 If-Match 기준)."""
    user_id = _uid(user)
    prof = await get_cm_client().get_profile(user_id) or {}
    _set_etag(response, prof.get("updated_at"))
    return {"alias": prof.get("nickname") or f"발명가-{user_id[:6]}"}


@router.put(
    "/api/v1/user/account/alias",
    status_code=200,
    response_model=AliasResponse,
    responses={**_ETAG_200, **_ERR_IF_MATCH},
)
async def set_alias(
    response: Response,
    body: AliasUpdateRequest,
    user: dict = Depends(get_current_user),
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> dict[str, Any]:
    """별명 변경 — If-Match 필수(무헤더 428 / 불일치 412, A-10). 응답에 새 ETag."""
    alias = body.alias.strip()
    if not alias:
        raise APIError(ErrorCode.validation_failed, 422, "alias required")
    cm = get_cm_client()
    user_id = _uid(user)
    prof = await cm.get_profile(user_id) or {}
    _check_if_match(if_match, prof.get("updated_at"))
    patched = await cm.patch_profile(user_id, [{"op": "add", "path": "/nickname", "value": alias}])
    _set_etag(response, patched.get("updated_at"))
    return {"alias": alias}


# ===========================================================================
# /user/works — work 컬렉션 ops (생성·목록)
# ===========================================================================


def _progress(maturity: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(maturity, dict):
        return {"phase": "discovery"}
    scores = maturity.get("scores") or {}
    if not isinstance(scores, dict):
        scores = {}
    overall = maturity.get("overall_score")
    return {
        "phase": "discovery",
        "progress": float(overall) if isinstance(overall, int | float) else None,
        "clarity": scores.get("clarity"),
        "completeness": scores.get("completeness"),
        "potential": scores.get("potential"),
    }


@router.post(
    "/api/v1/user/works",
    status_code=201,
    response_model=WorkCreateResponse,
    responses={**_LOCATION_201, **_ERR_CONFLICT},
)
async def works_new(
    response: Response,
    user: dict = Depends(get_current_user),
    idem_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    """새 work 생성 (CM /sessions → work_id). 201 + Location · Idempotency-Key 재시도."""
    user_id = _uid(user)
    action, replayed = await _idem_begin(user_id, "works", idem_key, response)
    if action == "replay":
        return replayed  # type: ignore[return-value]
    if action == "busy":
        raise APIError(ErrorCode.conflict, 409, "Idempotency-Key 처리 중 — 잠시 후 재시도")
    try:
        res = await get_cm_client().create_session(user_id)
        work_id = res.get("work_id")
        if not work_id:
            # 생성 성공인데 자원 위치를 못 주는 201 은 계약 구멍 → 내부 실패로 500.
            raise APIError(ErrorCode.internal, 500, "work 생성 실패 — CM 이 work_id 미반환")
    except Exception:
        await _idem_release(user_id, "works", idem_key)  # 실패 → 선점 해제(재시도 즉시 가능)
        raise
    location = f"/api/v1/works/{work_id}"
    response.headers["Location"] = location
    body = {"work_id": work_id, "created_at": res.get("created_at")}
    await _idem_finish(user_id, "works", idem_key, body, location)
    return body


@router.get("/api/v1/user/works", response_model=WorkBriefResponse)
async def works_brief(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """내 works 목록(brief). 최근 활동 순."""
    cm = get_cm_client()
    user_id = _uid(user)
    raw = await cm.list_sessions(user_id) or {}
    items: list[dict[str, Any]] = []
    for raw_item in raw.get("inventions") or []:
        if not isinstance(raw_item, dict) or "work_id" not in raw_item:
            continue
        wid = raw_item["work_id"]
        try:
            manifest = await cm.get_context_manifest(user_id, wid) or {}
            maturity = await cm.get_concept_maturity_model(user_id, wid)
            items.append(
                {
                    "work_id": wid,
                    "title": manifest.get("title") or f"발명 {wid[:8]}",
                    "progress": _progress(maturity if isinstance(maturity, dict) else None),
                    "last_activity_at": manifest.get("last_activity_at")
                    or manifest.get("updated_at"),
                    "created_at": manifest.get("created_at") or raw_item.get("created_at"),
                }
            )
        except Exception:  # noqa: BLE001
            log.warning("works_brief: item build failed work=%s", wid)
    items.sort(
        key=lambda x: x.get("last_activity_at") or x.get("created_at") or "",
        reverse=True,
    )
    return {"items": items}


# ===========================================================================
# /works/{work_id} — 진입점 (가벼운 식별 {work_id,title}, D9) · 메타 (detail / rename)
# ===========================================================================


@router.get("/api/v1/works/{work_id}", response_model=WorkEntryResponse)
async def work_entry(work_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """work 진입점 — 가벼운 식별({work_id,title}). 하위 자원은 고정 URL 템플릿으로 직접 구성(A-9). 상세는 meta."""
    cm = get_cm_client()
    user_id = _uid(user)
    manifest = await cm.get_context_manifest(user_id, work_id)
    if manifest is None:
        raise APIError(ErrorCode.work_not_found, 404, f"work {work_id} not found")
    return {
        "work_id": work_id,
        "title": manifest.get("title") or f"발명 {work_id[:8]}",
    }


@router.get("/api/v1/works/{work_id}/meta", response_model=WorkDetailResponse, responses=_ETAG_200)
async def work_info_detail(
    work_id: str, response: Response, user: dict = Depends(get_current_user)
) -> dict[str, Any]:
    """work 상세 (제목+상세 전부). ETag(manifest.updated_at) 동반 (PATCH 의 If-Match 기준)."""
    cm = get_cm_client()
    user_id = _uid(user)
    manifest = await cm.get_context_manifest(user_id, work_id)
    if manifest is None:
        raise APIError(ErrorCode.work_not_found, 404, f"work {work_id} not found")
    maturity = await cm.get_concept_maturity_model(user_id, work_id)
    _set_etag(response, manifest.get("updated_at"))
    return {
        "work_id": work_id,
        "title": manifest.get("title") or f"발명 {work_id[:8]}",
        "title_source": manifest.get("title_source") or "auto",
        "progress": _progress(maturity if isinstance(maturity, dict) else None),
        "last_activity_at": manifest.get("last_activity_at") or manifest.get("updated_at"),
        "created_at": manifest.get("created_at"),
        "updated_at": manifest.get("updated_at"),
    }


@router.patch(
    "/api/v1/works/{work_id}/meta",
    status_code=200,
    response_model=WorkDetailResponse,
    responses={**_ETAG_200, **_ERR_IF_MATCH},
)
async def work_info_rename(
    work_id: str,
    response: Response,
    body: MetaRenameRequest,
    user: dict = Depends(get_current_user),
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> dict[str, Any]:
    """제목 수정(title_source='user'). If-Match 필수(무헤더 428 / 불일치 412, A-10)."""
    title = body.title.strip()
    if not title:
        raise APIError(ErrorCode.validation_failed, 422, "title required")
    cm = get_cm_client()
    user_id = _uid(user)
    manifest = await cm.get_context_manifest(user_id, work_id)
    if manifest is None:
        raise APIError(ErrorCode.work_not_found, 404, f"work {work_id} not found")
    _check_if_match(if_match, manifest.get("updated_at"))
    ops = [
        {"op": "replace", "path": "/title", "value": title},
        {"op": "replace", "path": "/title_source", "value": "user"},
        {"op": "replace", "path": "/updated_at", "value": datetime.now(UTC).isoformat()},
    ]
    await cm.patch_context_manifest(user_id, work_id, ops)
    return await work_info_detail(work_id, response=response, user=user)  # type: ignore[arg-type]


# ===========================================================================
# works/{id} chain-surface reads (이관 ← DRO: phase / thread.messages / estimate read)
# 순수 CM read(+manifest write). 체인 트리거 없음 — roadmap 답변·media·WS·output 은 DRO/후속.
# ===========================================================================


@router.get("/api/v1/works/{work_id}/phase", response_model=PhaseStateResponse)
async def phase_current(work_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    cm = get_cm_client()
    user_id = _uid(user)
    manifest = await cm.get_context_manifest(user_id, work_id)
    if manifest is None:
        raise APIError(ErrorCode.work_not_found, 404, f"work {work_id} not found")
    phase = manifest.get("current_phase", "discovery")
    if phase == "drafting":
        body = await cm.download_document(user_id, work_id, "draft.docx")
        state = "complete" if body else "drafting"
    else:
        maturity = await cm.get_concept_maturity_model(user_id, work_id)
        overall = maturity.get("overall_score") if isinstance(maturity, dict) else None
        state = (
            "ready"
            if isinstance(overall, int | float) and overall >= _READY_THRESHOLD
            else "discovery"
        )
    return {
        "state": state,
    }


@router.patch("/api/v1/works/{work_id}/phase", status_code=200, response_model=PhaseStateResponse)
async def phase_transition(work_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """인자 없이 다음 단계로. ready→drafting (사용자 명시, 자동전이 없음)."""
    cm = get_cm_client()
    user_id = _uid(user)
    manifest = await cm.get_context_manifest(user_id, work_id)
    if manifest is None:
        raise APIError(ErrorCode.work_not_found, 404, f"work {work_id} not found")
    cur = manifest.get("current_phase", "discovery")
    nxt = "drafting" if cur == "discovery" else cur
    await cm.patch_context_manifest(
        user_id,
        work_id,
        [
            {"op": "replace", "path": "/current_phase", "value": nxt},
            {"op": "replace", "path": "/updated_at", "value": datetime.now(UTC).isoformat()},
        ],
    )
    return {
        "state": nxt,
    }


@router.get("/api/v1/works/{work_id}/thread/messages", response_model=ThreadMessagesResponse)
async def thread_messages(
    work_id: str,
    before: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """대화 이력 — cursor 페이지네이션 (before=<message_id>, 최근 limit개). resume 의 핵심.

    message id = work 내 0-based 위치(A-4) — append-only 라 안정. id 는 API 경계에서 파생(저장 X).
    before=<id> 면 그 id 이전 메시지만(즉 index < id).
    """
    cm = get_cm_client()
    data = await cm.get_conversation(_uid(user), work_id)
    msgs = (data or {}).get("messages") if isinstance(data, dict) else None
    raw = msgs if isinstance(msgs, list) else []
    items = [{**turn, "id": i} for i, turn in enumerate(raw)]  # id = 0-based 위치 파생
    if before is not None and before.isdigit():
        items = items[: int(before)]
    page = items[-limit:]
    next_cursor = str(page[0]["id"]) if len(items) > len(page) else None
    return {
        "items": page,
        "next_cursor": next_cursor,
    }


@router.get("/api/v1/works/{work_id}/estimate/roadmap", response_model=RoadmapPullResponse)
async def roadmap_pull(work_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    cm = get_cm_client()
    data = await cm.get_user_roadmap(_uid(user), work_id)
    items: list[Any] = list(data) if isinstance(data, list) else []
    return {"items": items}


@router.get("/api/v1/works/{work_id}/estimate/maturity", response_model=EstimateMaturityResponse)
async def estimate_maturity(work_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """CMM 현재값. 미계산 시 shaped null (값 None) 반환 — frontend 형태 안정."""
    cm = get_cm_client()
    data = await cm.get_concept_maturity_model(_uid(user), work_id)
    out = data if isinstance(data, dict) else {}
    scores = out.get("scores")
    return {
        **out,
        # B10 shaped-null: 3 필드 항상 존재. 미계산 시 overall/weights=None, scores=shaped 객체.
        "overall_score": out.get("overall_score"),
        "scores": scores
        if isinstance(scores, dict)
        else {"clarity": None, "completeness": None, "potential": None},
        "weights": out.get("weights"),
    }


# ===========================================================================
# estimate/roadmap/{item_id} (PATCH) — 답변 즉시 기록 + 체인 트리거 (sub-plan ② — DRO→Nexus 이관)
# ===========================================================================


@router.patch(
    "/api/v1/works/{work_id}/estimate/roadmap/{item_id}",
    status_code=200,
    response_model=RoadmapItem,
)
async def roadmap_submit(
    work_id: str,
    item_id: str,
    body: RoadmapSubmitRequest,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """로드맵 항목 답변 (REST). item_id 는 URI, 본문은 `{value}` 만 (B1 typed, strict).

    답은 사용자 입력 → Nexus 가 그 항목의 answer+status(satisfied)를 CM 통해 **즉시 기록**하고
    갱신된 항목을 반환. input_type 은 저장된 항목에서 도출(중복 안 받음). 성숙도·로드맵 재평가는
    handle_message 가 띄우는 체인(AI)이 담당, 결과는 WS model.maturity/model.roadmap 로.
    """
    # value 는 str | list[str] (RoadmapSubmitRequest strict — 숫자·dict·혼합리스트는 모델이 422).
    value = body.value
    content = ", ".join(value) if isinstance(value, list) else value
    if not content.strip():
        raise APIError(ErrorCode.validation_failed, 422, "value 비어있음")
    cm = get_cm_client()
    user_id = _uid(user)
    answer = {"value": value, "answered_at": datetime.now(UTC).isoformat()}
    # CM 이 id 로 atomic 갱신(락 안 find-by-id + write) — top-level array 의 index 경로는
    # 동시 전체-재작성(P02)에 어긋나 엉뚱한 항목에 쓸 수 있어 쓰지 않는다. 못 찾으면 None.
    item = await cm.set_roadmap_item(
        user_id, work_id, item_id, {"answer": answer, "status": "satisfied"}
    )
    if item is None:
        raise APIError(ErrorCode.not_found, 404, f"roadmap item '{item_id}' not found")
    await handle_message(
        user_id=user_id,
        work_id=work_id,
        content=content,
        user_turn_meta={
            "kind": "roadmap.answer",
            "roadmap_item_id": item_id,
            "input_type": item.get("input_type"),
        },
    )
    return {**item}


# ===========================================================================
# media — work 레벨 파일 (presigned S3 직접). 바이트는 우리 서버(Nexus·CM) 안 거침:
#   업로드   = 브라우저 → POST /media (업로드 티켓, Nexus 인증→CM 서명) → S3 직접 POST
#   다운로드 = GET /media/{id} (메타+다운로드 URL, CM 서명) → 클라/Actor 가 S3 직접 GET
# 메시지/chain 무관 — S3 prefix(sessions/{u}/{w}/media/) 가 진실, 장부 없음.
# ===========================================================================

_MIME_TO_EXT = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "application/pdf": "pdf",
}
# 안전한 확장자 = 영숫자 1~8자. '/' 등 키 분리자가 끼면 media/{id}.{ext} 가 nested 키가 되어
# list_media('/' 포함 키 skip)·quota 집계를 우회 → 그런 ext 는 거부하고 mime 표준 ext 로 폴백.
_SAFE_EXT_RE = re.compile(r"[a-z0-9]{1,8}")


def _derive_ext(filename: str | None, mime: str) -> str:
    """업로드 키 media/{id}.{ext} 의 확장자. filename 확장자를 쓰되 영숫자 1~8자만 인정,
    그 외(슬래시·공백·과길이·빈값)는 검증된 mime 의 표준 ext 로 폴백 (키 평탄성 보장)."""
    if filename and "." in filename:
        ext = filename.rsplit(".", 1)[1].strip().lower()
        if _SAFE_EXT_RE.fullmatch(ext):
            return ext
    return _MIME_TO_EXT.get(mime, "bin")


async def _require_work(cm: Any, user_id: str, work_id: str) -> None:
    if await cm.get_context_manifest(user_id, work_id) is None:
        raise APIError(ErrorCode.not_found, 404, f"work '{work_id}' not found")


@router.post(
    "/api/v1/works/{work_id}/media",
    status_code=201,
    response_model=PresignUploadResponse,
    responses={**_LOCATION_201, **_ERR_CONFLICT},
)
async def media_upload_url(
    work_id: str,
    body: MediaUploadUrlRequest,
    response: Response,
    user: dict = Depends(get_current_user),
    idem_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    """업로드 presigned POST 발급 — 브라우저가 S3 직접 POST. Idempotency-Key 재시도."""
    cm = get_cm_client()
    user_id = _uid(user)
    action, replayed = await _idem_begin(user_id, "media", idem_key, response)
    if action == "replay":
        return replayed  # type: ignore[return-value]
    if action == "busy":
        raise APIError(ErrorCode.conflict, 409, "Idempotency-Key 처리 중 — 잠시 후 재시도")
    try:
        await _require_work(cm, user_id, work_id)
        if body.mime not in venezia_media_config.allowed_mime():
            raise APIError(ErrorCode.validation_failed, 422, f"미허용 MIME: {body.mime!r}")
        cap = venezia_media_config.max_files_per_work()
        if len(await cm.list_media(user_id, work_id)) >= cap:
            raise APIError(ErrorCode.conflict, 409, f"work 당 미디어 상한 {cap} 초과")
        media_id = uuid.uuid4().hex
        ext = _derive_ext(body.filename, body.mime)
        max_bytes = venezia_media_config.max_file_bytes()
        ttl = venezia_media_config.put_ttl()
        presigned = await cm.request_presigned_put(
            user_id, work_id, media_id, ext, body.mime, max_bytes, ttl
        )
    except Exception:
        await _idem_release(user_id, "media", idem_key)  # 실패 → 선점 해제
        raise
    location = f"/api/v1/works/{work_id}/media/{media_id}"
    response.headers["Location"] = location
    result = {
        "media_id": media_id,
        "key": presigned["key"],
        "url": presigned["url"],
        "fields": presigned["fields"],
        "max_file_bytes": max_bytes,
        "ttl": ttl,
    }
    await _idem_finish(user_id, "media", idem_key, result, location)
    return result


@router.get("/api/v1/works/{work_id}/media", response_model=MediaListResponse)
async def media_list(work_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    cm = get_cm_client()
    user_id = _uid(user)
    await _require_work(cm, user_id, work_id)
    items: list[Any] = list(await cm.list_media(user_id, work_id))
    return {"items": items}


@router.get(
    "/api/v1/works/{work_id}/media/{media_id}",
    response_model=MediaDownloadResponse,
)
async def media_download_url(
    work_id: str, media_id: str, user: dict = Depends(get_current_user)
) -> dict[str, Any]:
    """미디어 자원 표현 — MediaItem 메타 + presigned 다운로드 URL(본문, redirect 아님).

    바이트는 클라/Actor 가 `url` 로 S3 에서 직접 GET.
    """
    cm = get_cm_client()
    user_id = _uid(user)
    await _require_work(cm, user_id, work_id)
    item = next(
        (
            it
            for it in await cm.list_media(user_id, work_id)
            if isinstance(it, dict) and it.get("media_id") == media_id
        ),
        None,
    )
    if item is None:
        raise APIError(ErrorCode.not_found, 404, f"media '{media_id}' not found")
    ttl = venezia_media_config.get_ttl()
    presigned = await cm.request_presigned_get(user_id, work_id, media_id, ttl)
    if presigned is None:
        raise APIError(ErrorCode.not_found, 404, f"media '{media_id}' not found")
    return {
        **item,
        "url": presigned["url"],
        "ttl": ttl,
    }


@router.delete("/api/v1/works/{work_id}/media/{media_id}", status_code=204)
async def media_delete(
    work_id: str, media_id: str, user: dict = Depends(get_current_user)
) -> Response:
    """미디어 삭제 — S3 객체 삭제. 멱등(없어도 204)."""
    cm = get_cm_client()
    await cm.delete_media(_uid(user), work_id, media_id)
    return Response(status_code=204)


# ===========================================================================
# output — 문서 (draft / proposal: build / preview / download). C6 — output/docx 재배선.
# build = Nexus→DRO POST /control/output (in-process docx, AI 없는 변환) → WS output.ready(비동기).
# 마스킹·결제 게이트는 Nexus(client 표면) 책임. proposal 3종 = 501(라우트 OPEN·로직 미구현, 후속).
# ===========================================================================

_DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _require_payment(token: str | None) -> None:
    """결제 게이트 placeholder — build + download. 본 마일스톤은 게이트 로직 부재(통과).
    향후: token(entitlement) 검증 실패 시 raise APIError(payment_required, 402, ...)."""
    return None


def _mask_substring(text: str | None, head_chars: int = 40) -> str | None:
    if not isinstance(text, str):  # None / 비-str(스키마 위반 IOM) → 안전 None (500 방지)
        return None
    body = text.strip()
    if len(body) <= head_chars:
        return body
    return f"{body[:head_chars]} --- (다운로드 시 전체 공개)"


def _claims_masked(iom: dict[str, Any]) -> list[str] | None:
    claims = iom.get("claims") if isinstance(iom, dict) else None
    # IOM schema: claims = list[{number, text}]. (구 {items:[...]} 형태도 흡수.)
    if isinstance(claims, list):
        items: Any = claims
    elif isinstance(claims, dict):
        items = claims.get("items")
    else:
        items = None
    if not isinstance(items, list):
        return None
    out: list[str] = []
    for c in items:
        body = (c.get("text") or c.get("body") or "") if isinstance(c, dict) else str(c)
        out.append(_mask_substring(body, head_chars=30) or "---")
    return out


@router.post(
    "/api/v1/works/{work_id}/output/draft", status_code=200, response_model=DraftBuildResponse
)
async def draft_build(
    work_id: str,
    user: dict = Depends(get_current_user),
    x_payment_token: str | None = Header(default=None, alias="X-Payment-Token"),
) -> dict[str, Any]:
    """정식 출원서 빌드 (결제 게이트). Nexus→DRO docx 빌드(동기) → WS output.ready(비동기 알림).

    현재 존재하는 IOM 을 DRO 가 docx 로 동기 변환·업로드한다. IOM 작성 workflow와 장시간
    비동기 job 모델은 별도 작성 단계 범위다. 현재 동기 계약은 200 결과 본문을 반환한다.
    """
    _require_payment(x_payment_token)
    user_id = _uid(user)
    result = await control_output(user_id, work_id, "draft")
    # 최근 활동 갱신 (mypage 메타 — Nexus 소유. DRO 는 context manifest 미접근).
    await get_cm_client().patch_context_manifest(
        user_id,
        work_id,
        [{"op": "add", "path": "/last_activity_at", "value": datetime.now(UTC).isoformat()}],
    )
    return {
        "document_id": result.get("document_id") or "draft",
        "filename": result.get("filename") or "draft.docx",
        "size_bytes": result.get("size_bytes") or 0,  # A-7: WS output.ready 와 동일 필드명
    }


@router.get("/api/v1/works/{work_id}/output/draft/preview", response_model=DraftPreviewResponse)
async def draft_preview(work_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """출원서 미리보기 — 백엔드 마스킹 JSON (무료). IOM schema 모양 read (title 은 ko)."""
    cm = get_cm_client()
    iom = await cm.get_iom(_uid(user), work_id)
    if iom is None:
        raise APIError(ErrorCode.content_not_ready, 404, "작성 콘텐츠 미준비")
    biblio = iom.get("bibliographic") or {}
    abstract = iom.get("abstract") or {}
    spec = iom.get("specification") or {}
    bg_art = spec.get("background_art") or {}
    # IOM schema 모양 read (title 은 ko, 본문은 spec 하위).
    title_obj = biblio.get("title")
    title = title_obj.get("ko") if isinstance(title_obj, dict) else title_obj
    fields = {
        "title": title if isinstance(title, str) else None,  # 공개 — 마스킹 없음
        "abstract": _mask_substring(
            abstract.get("text") if isinstance(abstract, dict) else None, 80
        ),
        "technical_field": _mask_substring(spec.get("technical_field"), 80),
        "background": _mask_substring(
            bg_art.get("description") if isinstance(bg_art, dict) else None, 60
        ),
        "specification": _mask_substring(spec.get("detailed_description"), 40),
        "claims": _claims_masked(iom),
    }
    present = [n for n, v in fields.items() if v]
    return {
        **fields,
        "sections_present": present,
    }


@router.get(
    "/api/v1/works/{work_id}/output/draft",
    response_class=Response,
    responses={
        200: {
            "description": "full docx (결제 게이트 통과)",
            "content": {_DOCX_MEDIA_TYPE: {"schema": {"type": "string", "format": "binary"}}},
            "headers": {
                "Content-Disposition": {
                    "schema": {"type": "string"},
                    "description": 'attachment; filename="draft.docx"',
                },
                "X-Download-Gate": {"schema": {"type": "string"}, "description": "게이트 상태"},
            },
        }
    },
)
async def draft_download(
    work_id: str,
    user: dict = Depends(get_current_user),
    x_payment_token: str | None = Header(default=None, alias="X-Payment-Token"),
) -> Response:
    """출원서 다운로드 — 결제 확인(placeholder) 후 full docx."""
    _require_payment(x_payment_token)
    cm = get_cm_client()
    body = await cm.download_document(_uid(user), work_id, "draft.docx")
    if body is None:
        raise APIError(ErrorCode.document_not_ready, 404, "draft.docx 미생성 — build 먼저")
    return Response(
        content=body,
        media_type=_DOCX_MEDIA_TYPE,
        headers={
            "Content-Disposition": 'attachment; filename="draft.docx"',
            "X-Download-Gate": "placeholder",
        },
    )


@router.post("/api/v1/works/{work_id}/output/proposal/build", status_code=501)
async def proposal_build(work_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    raise APIError(ErrorCode.not_implemented, 501, "경량 제안서 빌드는 후속 마일스톤")


@router.get("/api/v1/works/{work_id}/output/proposal/preview", status_code=501)
async def proposal_preview(work_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    raise APIError(ErrorCode.not_implemented, 501, "경량 제안서 미리보기는 후속 마일스톤")


@router.get("/api/v1/works/{work_id}/output/proposal/download", status_code=501)
async def proposal_download(work_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    raise APIError(ErrorCode.not_implemented, 501, "경량 제안서 다운로드는 후속 마일스톤")


# ===========================================================================
# WebSocket — /api/v1/works/{work_id}/thread/stream (쿠키 인증, Nexus)
# ===========================================================================


@router.websocket("/api/v1/works/{work_id}/thread/stream")
async def thread_stream(
    websocket: WebSocket,
    work_id: str,
    since_seq: int = Query(default=0, ge=0),
):
    """Production WS — 양방향. user_id 는 nx_access 쿠키에서 해석(SECURE)/고정(OPEN).

    인증: nx_access 쿠키가 handshake 에 자동 첨부 — 경로에 user_id 없음(위조 불가).
    연결 시 그 (user, work) 키의 DRO SSE consumer 를 ref-count 로 dial (event_consumer).
    """
    token = websocket.cookies.get(settings.ACCESS_COOKIE_NAME)

    # accept 먼저 → reject 시 실제 WS close code(4401/4404) 전달 (accept 전 close 는 HTTP 403 라
    # 클라가 코드 못 읽음 — Starlette/RFC 6455).
    await websocket.accept()

    user_id = user_id_from_token(token)
    if user_id is None:
        await websocket.close(code=4401)  # unauthorized
        return

    # connect work-guard: 없는/접근불가 work → 4404. cm 는 (user_id, work_id) 네임스페이스라
    # 미지/타인 work 모두 None — 4404 단일이 의도된 설계(구분 불가 + work 존재 비누출). 4403 불요.
    if await get_cm_client().get_context_manifest(user_id, work_id) is None:
        await websocket.close(code=4404)
        return

    # 소켓 수명 deadline = connect + 최대 수명 cap 단독 (C1f). access 토큰은 짧으므로(분 단위)
    # exp 에 묶지 않음 — handshake 시점 인증 후 cap 까지 유지(짧은 access 가 WS 조기 종료 안 하게).
    deadline = time.monotonic() + settings.WS_MAX_LIFETIME_MINUTES * 60

    registry = get_production_ws_registry()
    # add/acquire/replay 를 try 안에 둬 setup 실패 시에도 정리(누수 방지). 단 release 는
    # (user, work) **공유 refcount** 를 깎으므로 acquire 성공 시에만 — 아니면 같은 키의 다른
    # 연결 SSE consumer 를 잘못 cancel. remove 는 ws-identity 키라 무조건 안전(미-add=no-op).
    acquired = False
    try:
        await registry.add(user_id, work_id, websocket)
        await event_consumer.acquire(user_id, work_id)
        acquired = True
        if since_seq > 0:
            await registry.replay_since(user_id, work_id, websocket, since_seq)
        while True:
            timeout = max(0.0, deadline - time.monotonic())
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=timeout)
            except TimeoutError:
                # A-5: 정기 12h 수명 cap 도달 = 1001(going-away) — 같은 토큰으로 재연결 유도.
                # (인증 실패·만료는 4401, 없는/접근불가 work 는 4404 — 별개 의미.)
                await websocket.close(code=1001)
                break
            try:
                await ws_inbound.handle_inbound(websocket, raw, user_id, work_id)
            except Exception:  # noqa: BLE001
                log.exception("ws_inbound.failed user=%s work=%s", user_id, work_id)
    except WebSocketDisconnect:
        pass
    finally:
        await registry.remove(user_id, work_id, websocket)
        if acquired:
            await event_consumer.release(user_id, work_id)
