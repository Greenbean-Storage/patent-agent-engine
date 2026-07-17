"""각 phase 의 실제 HTTP/WS 호출 + assertion — 새 트리 (info/user/works).

11 phase (health/info/account/works/auth/work_resources/output/ws/ws_tape/error_envelope/secure). OPEN 모드
(인증 불요·고정 user_id) 기준. SECURE 전용 phase(401·토큰·WS 쿠키)는 `phase_secure` 로
구현 — OPEN stack 에서는 skip, SECURE stack(EP_TOKEN 실로그인 D7-a / mint CI D7-b)에서 실행.
각 phase 함수는 (httpx.AsyncClient, dro_url, ctx) → bool.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os

import httpx
import websockets

from .. import coverage

log = logging.getLogger(__name__)

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"


def _ok(m: str) -> None:
    print(f"  {GREEN}✓{RESET} {m}")


def _fail(m: str) -> None:
    print(f"  {RED}✗{RESET} {m}")


def _warn(m: str) -> None:
    print(f"  {YELLOW}!{RESET} {m}")


def _account_url() -> str:
    from venezia_topology import service_url  # noqa: PLC0415

    return service_url("nexus")


def _assert_error_envelope(body, code=None) -> bool:
    if not isinstance(body, dict):
        return False
    err = body.get("error")
    if not isinstance(err, dict) or "code" not in err or "message" not in err:
        return False
    return code is None or err["code"] == code


async def _new_work(http: httpx.AsyncClient) -> str:
    r = await http.post(f"{_account_url()}/api/v1/user/works")
    r.raise_for_status()
    return r.json()["work_id"]


# ─── health / auth_mode ───────────────────────────────────────────────────


async def phase_health(http, dro_url, ctx) -> bool:
    ok = True
    d = (await http.get(f"{dro_url}/health")).json()
    a = (await http.get(f"{_account_url()}/health")).json()
    am = a.get("auth_mode")
    ctx["auth_mode"] = am
    # DRO = 순수 내부 실행기 (인증 개념 없음) — status/service/llm_mode 만
    if d.get("status") == "ok" and d.get("service") == "dro":
        _ok(f"DRO health status=ok service=dro llm={d.get('llm_mode')}")
    else:
        _fail(f"DRO health 의외: {d}")
        ok = False
    # 인증은 Nexus 게이트웨이 소유 — auth_mode 는 Nexus health 가 단일 출처
    if am in ("open", "secure") and a.get("service") == "nexus":
        _ok(f"Nexus health auth_mode={am} service=nexus")
    else:
        _fail(f"Nexus health mismatch: {a}")
        ok = False
    return ok


# ─── info (전역·무인증) ─────────────────────────────────────────────────────


async def phase_info(http, dro_url, ctx) -> bool:
    ok = True
    r = await http.get(f"{_account_url()}/api/v1/info/providers")
    provs = r.json().get("providers") if r.status_code == 200 else None
    if (
        r.status_code == 200
        and isinstance(provs, list)
        and {"google", "naver", "kakao"} <= set(provs)
    ):
        _ok(f"GET /info/providers = {provs}")
    else:
        _fail(f"/info/providers 의외: {r.status_code} {provs}")
        ok = False
    r = await http.get(f"{_account_url()}/api/v1/info/attributions")
    if r.status_code == 200:
        _ok("GET /info/attributions 200")
    else:
        _fail(f"/info/attributions {r.status_code}")
        ok = False
    return ok


# ─── account (PII 0 — user_id/alias/providers) ─────────────────────────────


async def phase_account(http, dro_url, ctx) -> bool:
    ok = True
    acc = _account_url()
    r = await http.get(f"{acc}/api/v1/user/account")
    body = r.json() if r.status_code == 200 else {}
    if r.status_code == 200 and "user_id" in body and "alias" in body and "providers" in body:
        _ok(f"GET /user/account (user_id={str(body['user_id'])[:8]}…, alias={body['alias']!r})")
        # PII 0 검증 — email/name 노출 금지
        if "email" in body or "name" in body:
            _fail("account 에 PII(email/name) 노출 — PII 0 위배")
            ok = False
        else:
            _ok("account PII 0 (email/name 없음)")
    else:
        _fail(f"/user/account {r.status_code} {body}")
        return False
    # alias set/get — A-10: If-Match 필수 (현재 ETag 로 변경)
    g0 = await http.get(f"{acc}/api/v1/user/account/alias")
    etag0 = g0.headers.get("etag")
    r = await http.put(
        f"{acc}/api/v1/user/account/alias",
        json={"alias": "테스터"},
        headers={"If-Match": etag0} if etag0 else {},
    )
    if r.status_code == 200 and r.json().get("alias") == "테스터":
        _ok("PUT /user/account/alias → 테스터 (If-Match)")
    else:
        _fail(f"set alias {r.status_code} {r.text[:120]}")
        ok = False
    r = await http.get(f"{acc}/api/v1/user/account/alias")
    alias_etag = r.headers.get("etag")
    if r.status_code == 200 and r.json().get("alias") == "테스터":
        _ok("GET /user/account/alias = 테스터 (반영됨)")
    else:
        _warn(f"get alias {r.status_code} {r.json() if r.status_code == 200 else ''}")
    # A-10: 무 If-Match → 428
    r = await http.put(f"{acc}/api/v1/user/account/alias", json={"alias": "x"})
    if r.status_code == 428:
        _ok("PUT /alias 무 If-Match → 428 (precondition required)")
    else:
        _fail(f"alias 무헤더 428 기대인데 {r.status_code}")
        ok = False
    # 낡은 If-Match → 412
    r = await http.put(
        f"{acc}/api/v1/user/account/alias",
        json={"alias": "x"},
        headers={"If-Match": '"STALE-NOPE"'},
    )
    if r.status_code == 412:
        _ok(f"alias ETag={alias_etag} · 낡은 If-Match → 412")
    else:
        _fail(f"alias If-Match 412 기대인데 {r.status_code}")
        ok = False
    return ok


# ─── works (생성/목록/meta GET·PATCH) ───────────────────────────────────────


async def phase_works(http, dro_url, ctx) -> bool:
    ok = True
    acc = _account_url()
    r = await http.post(f"{acc}/api/v1/user/works")
    if r.status_code == 201 and r.json().get("work_id"):
        wid = r.json()["work_id"]
        ctx["work_id"] = wid
        if r.headers.get("location") == f"/api/v1/works/{wid}":
            _ok(f"POST /user/works → 201 + Location (work_id={wid[:8]}…)")
        else:
            _fail(f"works 201 인데 Location 불일치: {r.headers.get('location')}")
            ok = False
    else:
        _fail(f"works 생성 {r.status_code} {r.text[:120]}")
        return False
    # Idempotency-Key 재시도 → 같은 work_id (D6, CM 영속)
    r2 = await http.post(f"{acc}/api/v1/user/works", headers={"Idempotency-Key": "ep-ik-1"})
    r3 = await http.post(f"{acc}/api/v1/user/works", headers={"Idempotency-Key": "ep-ik-1"})
    if (
        r2.status_code == 201
        and r3.status_code == 201
        and r2.json().get("work_id") == r3.json().get("work_id")
    ):
        _ok("POST /user/works 같은 Idempotency-Key → 같은 work_id (재시도 안전)")
    else:
        _fail(f"IK 재시도 불일치: {r2.json().get('work_id')} vs {r3.json().get('work_id')}")
        ok = False
    r = await http.get(f"{acc}/api/v1/user/works")
    if r.status_code == 200 and isinstance(r.json().get("items"), list):
        _ok(f"GET /user/works items={len(r.json()['items'])}")
    else:
        _fail(f"works 목록 {r.status_code}")
        ok = False
    # 진입점 (가벼운 식별 {work_id, title}, A-9 — 탐색 링크 없음)
    r = await http.get(f"{acc}/api/v1/works/{wid}")
    if r.status_code == 200 and r.json().get("work_id") == wid and r.json().get("title"):
        _ok("GET /works/{id} 진입 (work_id + title)")
    else:
        _fail(f"work entry {r.status_code}: {r.text[:120]}")
        ok = False
    r = await http.get(f"{acc}/api/v1/works/{wid}/meta")
    meta_etag = r.headers.get("etag")
    if r.status_code == 200 and r.json().get("work_id") == wid:
        _ok(
            f"GET /works/{{id}}/meta (title={r.json().get('title')!r}, source={r.json().get('title_source')})"
        )
    else:
        _fail(f"meta {r.status_code}")
        ok = False
    if not meta_etag:
        _warn("GET /meta ETag 없음 (manifest.updated_at?)")
    # A-10: If-Match 필수 — 현재 ETag 로 변경
    r = await http.patch(
        f"{acc}/api/v1/works/{wid}/meta",
        json={"title": "이름변경"},
        headers={"If-Match": meta_etag} if meta_etag else {},
    )
    if (
        r.status_code == 200
        and r.json().get("title") == "이름변경"
        and r.json().get("title_source") == "user"
    ):
        _ok("PATCH /works/{id}/meta (title_source=user, If-Match)")
    else:
        _fail(f"rename {r.status_code} {r.text[:120]}")
        ok = False
    # A-10: 무 If-Match → 428
    r = await http.patch(f"{acc}/api/v1/works/{wid}/meta", json={"title": "x"})
    if r.status_code == 428:
        _ok("PATCH /meta 무 If-Match → 428")
    else:
        _fail(f"meta 무헤더 428 기대인데 {r.status_code}")
        ok = False
    # 낡은 If-Match → 412 (D7 낙관적 동시성)
    r = await http.patch(
        f"{acc}/api/v1/works/{wid}/meta",
        json={"title": "x"},
        headers={"If-Match": '"STALE-NOPE"'},
    )
    if r.status_code == 412:
        _ok("PATCH /meta 낡은 If-Match → 412")
    else:
        _fail(f"meta If-Match 412 기대인데 {r.status_code}")
        ok = False
    return ok


# ─── auth (OAuth authorize — URL 생성, IdP 미호출) ─────────────────────────


async def phase_auth(http, dro_url, ctx) -> bool:
    """authorize ×3 (URL+state, 실 IdP 미호출) + unknown provider 404.

    callback/connect 의 실 provider exchange 는 사람 로그인 필요 → release 수동 smoke (D7-a).
    """
    ok = True
    acc = _account_url()
    for prov in ("google", "naver", "kakao"):
        r = await http.get(f"{acc}/api/v1/user/auth/{prov}/authorize")
        body = r.json() if r.status_code == 200 else {}
        if r.status_code == 200 and body.get("authorization_url") and body.get("state"):
            _ok(f"GET /user/auth/{prov}/authorize → url+state")
        else:
            _fail(f"authorize {prov} {r.status_code} {r.text[:100]}")
            ok = False
    r = await http.get(f"{acc}/api/v1/user/auth/bogus/authorize")
    if r.status_code == 404:
        _ok("GET /user/auth/bogus/authorize → 404 (unknown provider)")
    else:
        _fail(f"unknown provider 의외: {r.status_code}")
        ok = False
    # refresh/logout 무쿠키 현재동작 — 별도 클라(공유 jar 오염·logout Set-Cookie 영향 차단).
    async with httpx.AsyncClient(timeout=15.0) as anon:
        rr = await anon.post(f"{acc}/api/v1/user/auth/refresh")
        if rr.status_code == 401:
            _ok("POST /user/auth/refresh (무쿠키) → 401")
        else:
            _fail(f"refresh 무쿠키 401 의외: {rr.status_code}")
            ok = False
        rl = await anon.post(f"{acc}/api/v1/user/auth/logout")
        if rl.status_code == 204:
            _ok("POST /user/auth/logout (무쿠키) → 멱등 204")
        else:
            _fail(f"logout 무쿠키 204 의외: {rl.status_code}")
            ok = False
    return ok


# ─── phase / thread / estimate / output / media (DRO) ──────────────────────


async def phase_work_resources(http, dro_url, ctx) -> bool:
    ok = True
    wid = ctx.get("work_id") or await _new_work(http)
    # phase
    r = await http.get(f"{_account_url()}/api/v1/works/{wid}/phase")
    if r.status_code == 200 and r.json().get("state") in (
        "discovery",
        "ready",
        "drafting",
        "complete",
    ):
        _ok(f"GET /phase state={r.json()['state']}")
    else:
        _fail(f"phase {r.status_code} {r.text[:120]}")
        ok = False
    # thread/messages
    r = await http.get(f"{_account_url()}/api/v1/works/{wid}/thread/messages")
    if r.status_code == 200 and "items" in r.json():
        _ok(f"GET /thread/messages items={len(r.json()['items'])}")
    else:
        _fail(f"thread/messages {r.status_code}")
        ok = False
    # estimate
    r = await http.get(f"{_account_url()}/api/v1/works/{wid}/estimate/roadmap")
    if r.status_code == 200 and "items" in r.json():
        _ok(f"GET /estimate/roadmap items={len(r.json()['items'])}")
    else:
        _fail(f"roadmap {r.status_code}")
        ok = False
    r = await http.get(f"{_account_url()}/api/v1/works/{wid}/estimate/maturity")
    if r.status_code == 200:
        _ok(f"GET /estimate/maturity (null={r.json() is None})")
    else:
        _fail(f"maturity {r.status_code}")
        ok = False
    # (output/draft·proposal 표면은 별도 phase_output 에서 검증 — C6 재배선)
    # media — presigned S3 직접 (Nexus 인증 → CM 서명 → 클라가 S3 직접 POST/GET, 바이트 서버 미경유)
    acc = _account_url()
    blob = b"\x89PNG\r\n\x1a\nendpoint-test"
    r = await http.post(
        f"{acc}/api/v1/works/{wid}/media",
        json={"filename": "hello.png", "mime": "image/png"},
    )
    if r.status_code == 201 and r.json().get("media_id") and r.json().get("url"):
        up = r.json()
        mid = up["media_id"]
        if r.headers.get("location") == f"/api/v1/works/{wid}/media/{mid}":
            _ok(f"POST /media → 201 + Location (media_id={mid[:8]}…)")
        else:
            _fail(f"media 201 인데 Location 불일치: {r.headers.get('location')}")
            ok = False
        # presigned POST 로 S3 에 직접 업로드 (서버측 POST — CORS 무관)
        s3 = await http.post(
            up["url"], data=up["fields"], files={"file": ("hello.png", blob, "image/png")}
        )
        if s3.status_code in (200, 201, 204):
            _ok("presigned POST → S3 직접 업로드 (바이트 서버 미경유)")
            r2 = await http.get(f"{acc}/api/v1/works/{wid}/media/{mid}")
            if r2.status_code == 200 and r2.json().get("url"):
                g = await http.get(r2.json()["url"])
                if g.status_code == 200 and g.content == blob:
                    _ok("GET /media/{id} → S3 직접 GET (bytes 일치)")
                else:
                    _fail(f"media S3 GET {g.status_code}")
                    ok = False
            else:
                _fail(f"media GET {r2.status_code}")
                ok = False
            d = await http.delete(f"{acc}/api/v1/works/{wid}/media/{mid}")
            if d.status_code == 204:
                _ok("DELETE /media/{id} (204)")
            else:
                _fail(f"media DELETE {d.status_code}")
                ok = False
        else:
            _fail(f"presigned S3 POST {s3.status_code} {s3.text[:120]}")
            ok = False
    else:
        _fail(f"media POST {r.status_code} {r.text[:120]}")
        ok = False
    # media list
    r = await http.get(f"{acc}/api/v1/works/{wid}/media")
    if r.status_code == 200 and "items" in r.json():
        _ok(f"GET /media items={len(r.json()['items'])}")
    else:
        _fail(f"media list {r.status_code}")
        ok = False
    # phase 전이 (state-flip; 작성 백엔드 미구현 — 현재 동작 검증). PATCH(본문 없음, 서버가 전이 결정)
    r = await http.patch(f"{acc}/api/v1/works/{wid}/phase")
    if r.status_code == 200 and r.json().get("state") in (
        "discovery",
        "ready",
        "drafting",
        "complete",
    ):
        _ok(f"PATCH /phase → state={r.json()['state']}")
    else:
        _fail(f"phase transition {r.status_code} {r.text[:120]}")
        ok = False
    # estimate/roadmap 답변: PATCH .../roadmap/{item_id} {value}. 항목 있으면 200 RoadmapItem(satisfied),
    # 갓 생성한 work 는 로드맵 미생성이라 PATCH → 404(현재 동작). 값 무효는 항목 조회 전 422.
    rm = await http.get(f"{acc}/api/v1/works/{wid}/estimate/roadmap")
    items = rm.json().get("items") if rm.status_code == 200 else None
    if items:
        iid = items[0]["id"]
        r = await http.patch(
            f"{acc}/api/v1/works/{wid}/estimate/roadmap/{iid}", json={"value": "테스트 답변"}
        )
        body = r.json()
        if r.status_code == 200 and body.get("status") == "satisfied" and "chains" not in body:
            _ok("PATCH /estimate/roadmap/{id} → 200 RoadmapItem(satisfied, chains 미노출)")
        else:
            _fail(f"roadmap answer {r.status_code} {r.text[:120]}")
            ok = False
    else:
        r = await http.patch(
            f"{acc}/api/v1/works/{wid}/estimate/roadmap/q-ep", json={"value": "테스트 답변"}
        )
        if r.status_code == 404 and _assert_error_envelope(r.json(), "not_found"):
            _ok("PATCH /estimate/roadmap/{id} (로드맵 미생성) → 404 not_found (현재 동작)")
        else:
            _warn(f"roadmap answer (no roadmap) 의외: {r.status_code}")
    r = await http.patch(f"{acc}/api/v1/works/{wid}/estimate/roadmap/q-ep", json={"value": ""})
    if r.status_code == 422 and _assert_error_envelope(r.json(), "validation_failed"):
        _ok("PATCH /estimate/roadmap/{id} 무효 → 422 validation_failed")
    else:
        _warn(f"roadmap answer 무효 의외: {r.status_code}")
    return ok


# ─── output (draft build/preview/download + proposal 501) ────────────────────


async def phase_output(http, dro_url, ctx) -> bool:
    """output/draft build·preview·download + proposal 501.

    핵심 = output.ready WS 통합 (client build → DRO/mock → RAW output_ready → event_mapper → 클라 WS).
    - dro:fake: mock /control/output 이 canned + output_ready emit → build 200 + WS output.ready (hard).
      mock 은 CM 미영속(stateless) → preview/download 는 documented 404 (현재 동작).
    - dro:real: IOM writer(P02.R99) 미구현이라 IOM 없음 → build/preview = documented 404 content_not_ready
      (실 build→output.ready→download 200 경로는 play SEED= 가 커버). IOM 존재 시 200 경로도 통과.
    - proposal 3종 = 501 (라우트 OPEN·로직 미구현, 양 모드). [[endpoint-verify-current-behavior]]
    """
    ok = True
    acc = _account_url()
    fake = ctx.get("dro_scope") == "fake"
    wid = await _new_work(http)

    # proposal 3종 → 501 (양 모드 불변 — 라우트 OPEN·로직 placeholder)
    r = await http.post(f"{acc}/api/v1/works/{wid}/output/proposal/build")
    if r.status_code == 501 and _assert_error_envelope(r.json(), "not_implemented"):
        _ok("POST /output/proposal/build → 501 not_implemented")
    else:
        _fail(f"proposal/build 의외: {r.status_code} {r.text[:100]}")
        ok = False
    for sub in ("preview", "download"):
        r = await http.get(f"{acc}/api/v1/works/{wid}/output/proposal/{sub}")
        if r.status_code == 501:
            _ok(f"GET /output/proposal/{sub} → 501")
        else:
            _fail(f"proposal/{sub} 의외: {r.status_code}")
            ok = False

    # draft/build + output.ready WS — WS 먼저 열어 Nexus event_consumer 가 DRO events dial 하게.
    ws_url = acc.replace("http", "ws") + f"/api/v1/works/{wid}/thread/stream"
    received: list[dict] = []
    stop = asyncio.Event()
    build_status = None
    try:
        async with websockets.connect(
            ws_url,
            additional_headers=(
                [("Cookie", f"nx_access={ctx['token']}")] if ctx.get("token") else None
            ),
        ) as ws:

            async def recv():
                # 프레임 간 공백(timeout)에 죽지 않고 stop 까지 계속 — cold work 의 첫 프레임 지연 대응.
                while not stop.is_set():
                    try:
                        received.append(json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0)))
                    except asyncio.TimeoutError:
                        continue
                    except websockets.ConnectionClosed:
                        break

            t = asyncio.create_task(recv())
            await asyncio.sleep(0.4)  # WS 연결 → Nexus event_consumer 가 DRO events dial
            rb = await http.post(f"{acc}/api/v1/works/{wid}/output/draft")
            build_status = rb.status_code
            loop = asyncio.get_event_loop()
            t0 = loop.time()
            while loop.time() - t0 < 15:
                await asyncio.sleep(0.5)
                if any(e.get("type") == "output.ready" for e in received):
                    break
            await asyncio.sleep(0.5)
            stop.set()
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await t
    except Exception as e:  # noqa: BLE001
        _fail(f"output build/WS exception: {e!r}")
        return False

    or_evt = next((e for e in received if e.get("type") == "output.ready"), None)
    if fake:
        if build_status == 200:
            _ok("POST /output/draft → 200 (mock-dro 동기 빌드 — 완료는 WS output.ready)")
        else:
            _fail(f"draft 빌드(fake) 의외: {build_status}")
            ok = False
        if or_evt is not None:
            d = or_evt.get("data") or {}
            if d.get("document_id") == "draft" and d.get("filename") == "draft.docx":
                _ok("WS output.ready (document_id=draft, filename=draft.docx)")
            else:
                _fail(f"output.ready data 의외: {d}")
                ok = False
        else:
            seen_types = {e.get("type") for e in received}
            _fail(f"WS output.ready 미수신 — dro:fake mock emit (hard). types={seen_types}")
            ok = False
    else:
        if build_status == 200:
            _ok("POST /output/draft → 200 (IOM 존재 — 실 빌드, 완료는 WS)")
            if or_evt is not None:
                _ok("WS output.ready")
            else:
                _warn("build 200 인데 output.ready 미수신 (타이밍)")
        elif build_status == 404:
            _ok(
                "POST /output/draft → 404 content_not_ready (IOM 미준비 — 현재 동작; 실빌드 play SEED=)"
            )
        else:
            _fail(f"draft 빌드(real) 의외: {build_status}")
            ok = False

    # draft/preview — IOM 있으면 200 마스킹, 없으면 404 content_not_ready (현재 동작)
    r = await http.get(f"{acc}/api/v1/works/{wid}/output/draft/preview")
    if r.status_code == 200:
        _ok("GET /output/draft/preview → 200 (마스킹 JSON)")
    elif r.status_code == 404 and _assert_error_envelope(r.json(), "content_not_ready"):
        _ok("GET /output/draft/preview → 404 content_not_ready (IOM 미준비 — 현재 동작)")
    else:
        _fail(f"draft/preview 의외: {r.status_code} {r.text[:100]}")
        ok = False

    # draft/download — docx 영속 있으면 200, 없으면 404 document_not_ready (현재 동작)
    r = await http.get(f"{acc}/api/v1/works/{wid}/output/draft")
    if r.status_code == 200:
        _ok("GET /output/draft → 200 (docx 영속)")
    elif r.status_code == 404 and _assert_error_envelope(r.json(), "document_not_ready"):
        _ok("GET /output/draft → 404 document_not_ready (미빌드/미영속 — 현재 동작)")
    else:
        _fail(f"draft 다운로드 의외: {r.status_code} {r.text[:100]}")
        ok = False

    return ok


# ─── WS thread/stream (nx_access 쿠키 자동 첨부, OPEN 은 쿠키 없이) ──────────


async def phase_ws(http, dro_url, ctx) -> bool:
    """full-cycle — message.send 후 chain 이 emit 하는 client WS 이벤트 수집·검증 (신 계약).

    현 P01/P02 발생: message.received(unicast ack) · work.progress(support/analysis 채널) ·
    message.reply. (P03~P06 미spawn → 나머지 4 채널·output.ready 미발생=future. model.maturity/
    model.roadmap 은 Nexus 가 CM fetch 로 생성 — dro:fake CM 빈값이라 미발생, invoke 가 매핑 커버.)
    재시도(같은 correlation_id 재send) 멱등 무에러 + 봉투 스키마(C4) 검증. heartbeat=native WS ping/pong.

    dro:fake 스택에선 message.reply(chain_completed→text=null)가 tape 로 결정적 → hard fail 승격.
    fresh work 무조건 사용 — playlist cursor 격리. deadline-drain(EP_WS_TIMEOUT, 기본 45s).
    """
    import os  # noqa: PLC0415

    from ._ws_schema import validate_ws_frame  # noqa: PLC0415

    ok = True
    wid = await _new_work(http)  # fresh work — dro:fake playlist cursor 격리 (full-real 도 등가)
    ws_url = _account_url().replace("http", "ws") + f"/api/v1/works/{wid}/thread/stream"
    deadline = float(os.environ.get("EP_WS_TIMEOUT", "45"))
    received: list[dict] = []
    stop = asyncio.Event()
    try:
        async with websockets.connect(
            ws_url,
            additional_headers=(
                [("Cookie", f"nx_access={ctx['token']}")] if ctx.get("token") else None
            ),
        ) as ws:

            async def recv():
                # 프레임 간 공백(timeout)에 죽지 않고 stop 까지 계속 — cold work 의 첫 프레임 지연 대응.
                while not stop.is_set():
                    try:
                        received.append(json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0)))
                    except asyncio.TimeoutError:
                        continue
                    except websockets.ConnectionClosed:
                        break

            t = asyncio.create_task(recv())
            await asyncio.sleep(0.2)
            corr = "ep-ws-1"  # 멱등키 — 재시도는 같은 값으로 재send
            await ws.send(
                json.dumps(
                    {
                        "action": "message.send",
                        "data": {
                            "content": "안녕하세요, 발명 아이디어가 있습니다",
                            "correlation_id": corr,
                        },
                    }
                )
            )
            loop = asyncio.get_event_loop()
            t0 = loop.time()
            while loop.time() - t0 < deadline:
                await asyncio.sleep(1.0)
                if any(e.get("type") == "message.reply" for e in received):
                    break
            # 재시도 — 같은 correlation_id 로 재send(멱등 dedup) → 재-ack, 새 turn/spawn·system.error 없어야.
            await ws.send(
                json.dumps(
                    {
                        "action": "message.send",
                        "data": {
                            "content": "안녕하세요, 발명 아이디어가 있습니다",
                            "correlation_id": corr,
                        },
                    }
                )
            )
            await asyncio.sleep(2.0)
            stop.set()
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await t
        types = {e.get("type") for e in received}

        def seen(name: str) -> bool:
            return name in types

        # C4 — 수신 프레임 전부 봉투+payload 스키마 검증 (scope/subject_id 잔존·잘못된 type 도 적발)
        schema_errs = [
            f"{fr.get('type')!r}: {errs}" for fr in received if (errs := validate_ws_frame(fr))
        ]
        if schema_errs:
            _fail(f"WS 봉투 스키마 위반: {schema_errs[:5]}")
            ok = False
        else:
            _ok(f"WS 봉투 스키마 적합 ({len(received)} frames, scope/subject_id 없음)")
        # 핵심 (hard)
        if seen("message.received"):
            _ok("WS message.send → message.received (unicast ack)")
        else:
            _fail(f"WS no message.received (types={types})")
            ok = False
        # chain 구동 (현 FIXTURE 발생분)
        chans: set[str] = {
            ch
            for e in received
            if e.get("type") == "work.progress"
            for ch in [(e.get("data") or {}).get("channel")]
            if isinstance(ch, str)
        }
        valid = {"support", "analysis", "research", "thinking", "drafting", "review"}
        if chans and chans <= valid:
            _ok(f"work.progress channels={sorted(chans)} (현 P01/P02)")
        else:
            _warn(f"work.progress 채널 미발생/의외: {sorted(chans)}")
        hard_timing = ctx.get("dro_scope") == "fake"  # tape = 결정적 → warn→fail 승격
        if seen("message.reply"):
            _ok("WS message.reply (응답완료)")
        elif hard_timing:
            _fail("WS message.reply 미발생 — dro:fake tape 는 결정적 (hard)")
            ok = False
        else:
            _warn("WS message.reply 미발생 (FIXTURE chain 타이밍)")
        # model.* 는 Nexus 가 CM fetch 로 생성 — dro:fake 는 CM 빈값이라 미발생(skip 규약, 매핑은 invoke).
        for ev, label in (("model.maturity", "성숙도"), ("model.roadmap", "로드맵")):
            if seen(ev):
                _ok(f"WS {ev} ({label})")
            elif hard_timing:
                _ok(f"WS {ev} skip — dro:fake CM 빈값(미발생, 매핑은 invoke 커버)")
            else:
                _warn(f"WS {ev} 미발생 (FIXTURE chain 타이밍)")
        if seen("output.ready"):
            _ok("WS output.ready (작성 백엔드 활성)")
        # strict inbound — 정상 message.send(+멱등 재시도) 엔 system.error 없어야
        if seen("system.error"):
            _warn("정상 inbound 후 system.error 관측")
        else:
            _ok("정상 inbound (message.send + 멱등 재시도) → system.error 없음")
    except Exception as e:  # noqa: BLE001
        _fail(f"WS exception: {e!r}")
        ok = False
    return ok


# ─── error envelope ────────────────────────────────────────────────────────


async def phase_error_envelope(http, dro_url, ctx) -> bool:
    ok = True
    # 404 not_found — 없는 work
    r = await http.get(f"{_account_url()}/api/v1/works/does-not-exist/meta")
    if r.status_code == 404 and _assert_error_envelope(r.json(), "work_not_found"):
        _ok("GET /works/없는id/meta → 404 work_not_found")
    else:
        _fail(f"404 envelope 의외: {r.status_code} {r.text[:120]}")
        ok = False
    # 422 validation — alias 빈값
    r = await http.put(f"{_account_url()}/api/v1/user/account/alias", json={"alias": ""})
    if r.status_code == 422 and _assert_error_envelope(r.json(), "validation_failed"):
        _ok("PUT /account/alias 빈값 → 422 validation_failed")
    else:
        _warn(f"422 의외: {r.status_code}")
    # (output/draft error 경로[content_not_ready/document_not_ready]는 phase_output 에서 검증 — C6)
    return ok


def _mint_token(user_id: str = "00000000-0000-0000-0000-00000000open") -> str:
    """공유 secret 으로 access 토큰 mint — SECURE CI 자동화(D7-b). `create_access_token` 미러(typ=access). stub IdP 없음."""
    import jwt  # noqa: PLC0415
    from datetime import UTC, datetime, timedelta  # noqa: PLC0415

    secret = os.environ.get("JWT_SECRET_KEY") or "dev-only-jwt-secret-NOT-FOR-PRODUCTION-USE"
    now = datetime.now(UTC)
    return jwt.encode(  # nosemgrep
        {"sub": user_id, "typ": "access", "iat": now, "exp": now + timedelta(hours=1)},
        secret,
        algorithm="HS256",
    )


# ─── SECURE (auth 필수) — OPEN 이면 skip ────────────────────────────────────


async def phase_secure(http, dro_url, ctx) -> bool:
    """SECURE 전용 — 무토큰→401, 토큰→200, WS 쿠키. OPEN 이면 skip.

    토큰 = EP_TOKEN(실 로그인, D7-a) 또는 mint(CI, D7-b). stub IdP 없음.
    """
    if ctx.get("auth_mode") != "secure":
        _ok("SECURE phase skip (OPEN 모드 — 보호표면 무인증)")
        return True
    ok = True
    acc = _account_url()
    tok = ctx.get("token")
    # 1. 무토큰 → 401
    async with httpx.AsyncClient(timeout=15.0) as anon:
        r = await anon.get(f"{acc}/api/v1/user/account")
        if r.status_code == 401:
            _ok("무토큰 GET /user/account → 401")
        else:
            _fail(f"무토큰 401 의외: {r.status_code}")
            ok = False
    # 2. 토큰 → 200 (http 클라에 nx_access 쿠키 부착됨)
    r = await http.get(f"{acc}/api/v1/user/account")
    if r.status_code == 200 and "user_id" in r.json():
        _ok("토큰 GET /user/account → 200")
    else:
        _fail(f"토큰 200 의외: {r.status_code} {r.text[:100]}")
        ok = False
    # 3. WS 쿠키 — 무토큰 거부 / 토큰 accept
    wid = ctx.get("work_id") or await _new_work(http)
    ws_url = _account_url().replace("http", "ws") + f"/api/v1/works/{wid}/thread/stream"
    _valid_ws = {
        "message.received",
        "message.reply",
        "work.progress",
        "work.failed",
        "model.maturity",
        "model.roadmap",
        "output.ready",
        "system.resync_required",
        "system.error",
    }
    try:
        async with websockets.connect(ws_url) as ws:
            # 서버가 accept-then-close(4401) → recv 가 ConnectionClosed 로 거부 신호.
            await asyncio.wait_for(ws.recv(), timeout=5)
        _fail("무토큰 WS 가 거부되지 않음 (4401 기대)")
        ok = False
    except TimeoutError:  # 서버가 close 안 함 = 회귀 (timeout 으로 가리지 않음)
        _fail("무토큰 WS: 서버가 close 안 함 — 4401 기대인데 timeout")
        ok = False
    except websockets.ConnectionClosed as e:  # accept-then-close → close code 도달
        if e.code == 4401:
            _ok("무토큰 WS → close 4401")
        else:
            _warn(f"무토큰 WS close 코드 {e.code} (4401 기대)")
    except Exception as e:  # noqa: BLE001  (handshake-reject 등도 거부로 인정)
        _ok(f"무토큰 WS → 거부 ({type(e).__name__})")
    if tok:
        try:
            async with websockets.connect(
                ws_url, additional_headers=[("Cookie", f"nx_access={tok}")]
            ) as ws:
                await ws.send(
                    json.dumps(
                        {
                            "action": "message.send",
                            "data": {"content": "보안 phase 확인", "correlation_id": "ep-sec-1"},
                        }
                    )
                )
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                if msg.get("type") in _valid_ws and "scope" not in msg:
                    _ok(f"토큰 WS 쿠키 accept → {msg.get('type')} (봉투 v2)")
                else:
                    _warn(f"토큰 WS 응답 의외: {msg.get('type')}")
        except Exception as e:  # noqa: BLE001
            _fail(f"토큰 WS exception: {e!r}")
            ok = False
    return ok


def _detect_dro_scope() -> str:
    """profile 의 dro knob — endpoint 는 이 값으로만 분기 (Nexus client 표면 검증은 불변).

    Makefile 이 DEPLOYMENT_FILE 전달 (play 선례). 부재/예외 = "real" (보수적).
    """
    try:
        from venezia_deployment.runtime import value  # noqa: PLC0415

        return str(value("dro"))
    except Exception:  # noqa: BLE001
        return "real"


def _phase_map() -> dict:
    from .ws_tape import phase_ws_tape  # noqa: PLC0415 — 순환 import 회피 (ws_tape 가 본 모듈 헬퍼 사용)

    return {
        "health": phase_health,
        "info": phase_info,
        "account": phase_account,
        "works": phase_works,
        "auth": phase_auth,
        "work_resources": phase_work_resources,
        "output": phase_output,
        "ws": phase_ws,
        "ws_tape": phase_ws_tape,
        "error_envelope": phase_error_envelope,
        "secure": phase_secure,
    }


async def run_all(
    dro_url: str, phases: list[str], token: str | None = None, tape: str | None = None
) -> int:
    # auth_mode 선조회 → SECURE 면 토큰 확보 (EP_TOKEN 실로그인 D7-a / mint CI D7-b).
    # 인증은 Nexus 게이트웨이 소유 — auth_mode 는 Nexus /health 에서 (DRO 는 인증 개념 없음).
    auth_mode = "open"
    try:
        async with httpx.AsyncClient(timeout=10.0) as _p:
            auth_mode = ((await _p.get(f"{_account_url()}/health")).json() or {}).get(
                "auth_mode", "open"
            )
    except Exception:  # noqa: BLE001
        pass
    tok = token or os.environ.get("EP_TOKEN")
    if auth_mode == "secure" and not tok:
        tok = _mint_token()
    cookies = {"nx_access": tok} if tok else {}
    dro_scope = _detect_dro_scope()
    print("\n" + "━" * 76)
    print("  api-check — 외부 인터페이스 (새 트리: info/user/works)")
    print(
        f"  DRO URL: {dro_url}  ·  auth_mode={auth_mode}  ·  token={'있음' if tok else '없음'}"
        f"  ·  dro={dro_scope}"
    )
    print(f"  phases:  {', '.join(phases)}")
    print("━" * 76 + "\n")
    ctx: dict = {"auth_mode": auth_mode, "token": tok, "dro_scope": dro_scope, "tape": tape}
    results: dict[str, bool] = {}
    phase_map = _phase_map()
    async with httpx.AsyncClient(timeout=60.0, cookies=cookies) as http:
        for phase in phases:
            print(f"[{phase}]")
            fn = phase_map.get(phase)
            if fn is None:
                _fail(f"unknown phase: {phase}")
                results[phase] = False
                print()
                continue
            try:
                results[phase] = await fn(http, dro_url, ctx)
            except Exception as e:  # noqa: BLE001
                _fail(f"phase exception: {e!r}")
                results[phase] = False
            print()
    print("━" * 76)
    n_pass = sum(1 for v in results.values() if v)
    for phase, ok in results.items():
        mark = f"{GREEN}✓{RESET}" if ok else f"{RED}✗{RESET}"
        print(f"  {mark} {phase}")
    print("━" * 76)
    # coverage registry cross-check (spec parity) + 매트릭스 — D5: drift=fail 하되 완주
    drift = coverage.cross_check_spec()
    coverage.summary(results, scope=dro_scope)
    if drift:
        print(f"\n{RED}❌ coverage cross-check drift ({len(drift)}):{RESET}")
        for d in drift:
            print(f"  {d}")
    if n_pass == len(results) and not drift:
        print(f"\n{GREEN}✅ ALL {len(results)} phases passed + coverage cross-check OK{RESET}\n")
        return 0
    if n_pass != len(results):
        print(f"\n{RED}❌ {len(results) - n_pass}/{len(results)} phases failed{RESET}")
    print()
    return 1
