"""probe exercise — 실 CM 의 모든 API 를 전수 호출 (블랙박스 라이브 검증).

CM `/openapi.json` 으로 전 endpoint(분모)를 열거하고, 임시 세션에 컨텍스트 내 모든 파일에 대해
모든 API(정상 + 에러)를 호출한다. 라인 계측이 아니라 **API 표면 전수** — "CM 코드 다 활용".
정상 경로는 실제 자원(세션·chain·RT)을 만들어 그 id 로, 에러 경로는 더미 id 로 호출한다.

CM 은 내부 서비스(JWT 미검증)라 인증 불요 — OPEN/SECURE 어느 stack 이든 동작(mode-agnostic).
끝나면 임시 세션을 정리(clean)한다.
"""

from __future__ import annotations

from typing import Any

import httpx

from .._common import CM_URL, OPEN_USER_ID

_HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
# 자원이 먼저 생겨야 read/patch 가 의미있게 동작 → 생성(POST/PUT) 먼저, DELETE 마지막.
_METHOD_ORDER = {"POST": 0, "PUT": 1, "PATCH": 2, "GET": 3, "DELETE": 4}


async def fetch_endpoints(http: httpx.AsyncClient, cm_url: str) -> list[tuple[str, str]]:
    """CM /openapi.json 에서 (METHOD, path-template) 전수 — coverage 의 분모."""
    r = await http.get(f"{cm_url}/openapi.json")
    r.raise_for_status()
    spec = r.json()
    eps: list[tuple[str, str]] = []
    for path, ops in (spec.get("paths") or {}).items():
        for method in ops:
            if method.upper() in _HTTP_METHODS:
                eps.append((method.upper(), path))
    return eps


def _ctx(user_id: str, work_id: str) -> dict[str, str]:
    """path param 치환용 — 의존 자원 id 는 setup 에서 실제로 생성한 값."""
    return {
        "user_id": user_id,
        "work_id": work_id,
        "chain_id": "probe-chain",
        "rt_id": "probe-rt",
        "persona": "02.director",
        "name": "analysis",  # 02.director 의 valid dialog name
        "drawing_id": "probe-d",
        "filename": "probe.txt",
        "provider": "google",
        "provider_sub": "probe-sub",
        "idx": "0",
        "ext": "png",
        "family_id": "probe-fam",  # users/refresh-tokens (C1)
        "key_hash": "probe-kh",  # users/idempotency (D6)
        "media_id": "probe-m",  # media DELETE
        "item_id": "probe-item",  # user-roadmap item PATCH
    }


def _fill(path_template: str, ctx: dict[str, str]) -> str | None:
    """{param} 를 ctx 로 치환. 못 채운 param 이 남으면 None (skip)."""
    out = path_template
    for k, v in ctx.items():
        out = out.replace("{" + k + "}", v)
    return None if "{" in out else out


def _body(method: str, path: str) -> tuple[Any, Any]:
    """(json, files) 고정 샘플. 의도: 각 endpoint 가 crash 없이 실행되게 하는 최소 body."""
    if method == "PATCH":
        return [{"op": "add", "path": "/probe", "value": 1}], None
    if path.endswith("/user-roadmap"):  # top-level array
        return [], None
    if path.endswith("/media-{idx}.{ext}") or path.endswith("/outputs/{filename}"):
        return None, {"file": ("probe.bin", b"probe-bytes", "application/octet-stream")}
    if path.endswith("/runtime"):  # create chain
        return {
            "chain_id": "probe-chain",
            "pipeline_id": "P02.R00.PROBE",
            "persona": 2,
            "trigger": {"kind": "probe"},
        }, None
    if path.endswith("/conversation/append"):
        return {"role": "user", "content": "probe"}, None
    if path.endswith("/rts"):  # create RT
        return {"rt_id": "probe-rt", "persona": 2, "step_id": "s0"}, None
    if path.endswith("/queue/push"):
        return {"rt_id": "probe-rt", "chain_id": "probe-chain"}, None
    if path.endswith("/trail"):
        return {"event": "probe"}, None
    if path.endswith("/agent_state"):
        # vendor 원형 envelope (컨텍스트 ② — CM 은 body pass-through + persona/updated_at 스탬프)
        return {"schema_version": 1, "vendor": "fixture", "model": "probe", "items": []}, None
    if path.endswith("/queue/pop"):
        return None, None
    if path.endswith("/queue/release"):  # rt_id 별 lease 해제 (구 clear_inflight 폐기)
        return {"rt_id": "probe-rt"}, None
    if path.endswith("/identities/{provider}/{provider_sub}"):
        return {"user_id": OPEN_USER_ID}, None
    if path.endswith("/refresh-tokens/{user_id}/{family_id}"):  # PUT family (C1)
        return {"current_jti": "probe-jti"}, None
    if path.endswith("/refresh-tokens/{user_id}/{family_id}/rotate"):
        return {"expected_jti": "probe-jti", "new_jti": "probe-jti2"}, None
    return {"probe": 1}, None  # 기본 write body (manifest/model/dialog/profile 등)


async def exercise_session(
    http: httpx.AsyncClient,
    cm_url: str,
    user_id: str,
    work_id: str,
    endpoints: list[tuple[str, str]],
) -> dict[str, Any]:
    """기존 임시 세션(work_id)에 전 endpoint 호출. POST /sessions·DELETE 세션은 caller 담당.

    반환: hit(set) · failures(5xx/네트워크) · status_counts. crash(5xx) 0 + 전 endpoint 도달이 목표.
    """
    ctx = _ctx(user_id, work_id)
    hit: set[tuple[str, str]] = set()
    failures: list[str] = []
    status_counts: dict[str, int] = {"2xx": 0, "4xx": 0, "other": 0}

    def _ordered(eps: list[tuple[str, str]]) -> list[tuple[str, str]]:
        return sorted(eps, key=lambda mp: _METHOD_ORDER.get(mp[0], 9))

    for method, path in _ordered(endpoints):
        # 세션 lifecycle(생성/삭제)은 caller 가 별도 커버 — 나머지(/health 포함) 전부 호출.
        if (method, path) == ("POST", "/sessions"):
            continue
        if method == "DELETE" and path == "/sessions/{user_id}/{work_id}":
            continue
        concrete = _fill(path, ctx)
        if concrete is None:
            continue  # 치환 못한 param — 분모에서 (caller 가 missing 으로 보고)
        json_body, files = _body(method, path)
        params = {"confirm": "true"} if method == "DELETE" else None
        try:
            r = await http.request(
                method, f"{cm_url}{concrete}", json=json_body, files=files, params=params
            )
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{method} {path} → 네트워크/예외: {exc}")
            continue
        hit.add((method, path))
        if 200 <= r.status_code < 300:
            status_counts["2xx"] += 1
        elif 400 <= r.status_code < 500:
            status_counts["4xx"] += 1
        else:
            status_counts["other"] += 1
            failures.append(f"{method} {path} → status {r.status_code} (서버 오류/예상밖)")

    # media 자원 생성 — presign-put(유효 body) → 발급된 presigned POST 로 S3 직접 업로드(브라우저
    # 흐름 모사). presign 은 URL 만 발급(쓰기 0)이라 CM-API 만으론 media 객체가 안 생김 → 구조검증
    # (media resource-type)을 위해 실제 업로드 1건. 세션 정리(clean)가 함께 지움.
    try:
        pp = await http.post(
            f"{cm_url}/sessions/{user_id}/{work_id}/media/presign-put",
            json={
                "media_id": "probe-m",
                "ext": "png",
                "mime": "image/png",
                "max_bytes": 1_048_576,
                "ttl": 300,
            },
        )
        if pp.status_code == 200:
            d = pp.json()
            up = await http.post(
                d["url"],
                data=d["fields"],
                files={"file": ("probe.png", b"\x89PNG\r\n probe-bytes", "image/png")},
            )
            if not 200 <= up.status_code < 300:
                failures.append(f"media S3 업로드 → status {up.status_code}")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"media presign/upload → {exc}")

    # 명시적 에러 경로 (없는 자원 → 404) — CM 의 에러 분기 활용
    err_checks = [
        ("GET", f"/sessions/{user_id}/{work_id}/runtime/02.director/NOPE/rts/NOPE", 404),
        ("GET", f"/sessions/{user_id}/{work_id}/chains/NOPE/rts/NOPE", 404),
    ]
    error_results: list[str] = []
    for method, concrete, expect in err_checks:
        try:
            r = await http.request(method, f"{cm_url}{concrete}")
        except Exception as exc:  # noqa: BLE001
            error_results.append(f"{method} {concrete} → 예외 {exc}")
            continue
        mark = "✓" if r.status_code == expect else "✗"
        error_results.append(f"{mark} {method} (dummy id) → {r.status_code} (기대 {expect})")

    return {
        "hit": hit,
        "failures": failures,
        "status_counts": status_counts,
        "error_results": error_results,
    }


def coverage(endpoints: list[tuple[str, str]], hit: set[tuple[str, str]]) -> dict[str, Any]:
    total = set(endpoints)
    missing = sorted(f"{m} {p}" for m, p in (total - hit))
    return {"total": len(total), "hit": len(total & hit), "missing": missing}


async def run_exercise(user_id: str = OPEN_USER_ID, cm_url: str = CM_URL) -> int:
    async with httpx.AsyncClient(timeout=30) as http:
        try:
            endpoints = await fetch_endpoints(http, cm_url)
        except Exception:  # noqa: BLE001
            print(
                "✗ CM /openapi.json 실패 — stack 미가동? "
                "`make deploy init llm fake auth open && make up` 먼저."
            )
            return 1
        # 세션 생성 (POST /sessions 커버)
        inv = (await http.post(f"{cm_url}/sessions", json={"user_id": user_id})).json()["work_id"]
        hit: set[tuple[str, str]] = {("POST", "/sessions")}
        try:
            res = await exercise_session(http, cm_url, user_id, inv, endpoints)
            hit |= res["hit"]
        finally:
            d = await http.delete(f"{cm_url}/sessions/{user_id}/{inv}", params={"confirm": "true"})
            if 200 <= d.status_code < 300:
                hit.add(("DELETE", "/sessions/{user_id}/{work_id}"))
        cov = coverage(endpoints, hit)
        _print(cov, res)
        ok = not res["failures"] and not cov["missing"]
        return 0 if ok else 1


def _print(cov: dict, res: dict) -> None:
    pct = (cov["hit"] / cov["total"] * 100) if cov["total"] else 0.0
    sc = res["status_counts"]
    print(
        f"CM API 전수: {cov['hit']}/{cov['total']}  ({pct:.0f}%)  [2xx {sc['2xx']} · 4xx {sc['4xx']}]"
    )
    for e in res["error_results"]:
        print(f"  에러경로 {e}")
    if cov["missing"]:
        print(f"\n✗ 미호출 endpoint ({len(cov['missing'])}):")
        for m in cov["missing"]:
            print(f"  - {m}")
    if res["failures"]:
        print(f"\n✗ 호출 실패/서버오류 ({len(res['failures'])}):")
        for f in res["failures"]:
            print(f"  - {f}")
    print()
    print(
        "✅ CM API 전수 통과" if not cov["missing"] and not res["failures"] else "❌ 미달 — 위 확인"
    )
