"""probe verify — probe 트랙의 단일 게이트 (실 CM 블랙박스).

이미 make up 된 stack 의 CM 에 임시 세션 하나를 만들어:
  (가) exercise — CM 의 모든 API 전수 호출 (컨텍스트 내 모든 파일에 모든 API)
  (나) structure — 그 세션의 실제 S3 구조를 scaffolding + manifest 와 대조 (resource-type ≥99%)
둘 다 통과해야 exit 0. 끝나면 임시 세션 정리(clean). CM 무인증 → OPEN/SECURE 무관(mode-agnostic).

라인-커버리지 아님 — 그건 invoke 트랙의 일. 여기는 실 CM 의 API 표면 + 메모리 구조 검증.
"""

from __future__ import annotations

from typing import Any

import httpx

from .._common import CM_URL, OPEN_USER_ID
from .._structure import verify_structure
from . import exercise as ex


async def _get_json(http: httpx.AsyncClient, url: str) -> Any:
    try:
        r = await http.get(url)
    except Exception:  # noqa: BLE001
        return None
    return r.json() if r.status_code == 200 else None


async def run_verify(user_id: str = OPEN_USER_ID, cm_url: str = CM_URL) -> int:
    async with httpx.AsyncClient(timeout=30) as http:
        try:
            endpoints = await ex.fetch_endpoints(http, cm_url)
        except Exception:  # noqa: BLE001
            print(
                "✗ CM /openapi.json 실패 — stack 미가동? "
                "`make deploy init llm fake auth open && make up` 먼저 띄우세요."
            )
            return 1

        inv = (await http.post(f"{cm_url}/sessions", json={"user_id": user_id})).json()["work_id"]
        hit: set[tuple[str, str]] = {("POST", "/sessions")}
        try:
            ex_res = await ex.exercise_session(http, cm_url, user_id, inv, endpoints)
            hit |= ex_res["hit"]
            # 같은 세션의 실제 구조 검증 (exercise 가 전 resource 를 채워둠)
            base = f"{cm_url}/sessions/{user_id}/{inv}"
            tree = (await http.get(f"{base}/tree")).json().get("keys", [])
            runtime_manifest = await _get_json(http, f"{base}/runtime")
            outputs_manifest = await _get_json(http, f"{base}/outputs/manifest")
            st_res = verify_structure(tree, runtime_manifest, outputs_manifest)
        finally:
            d = await http.delete(f"{cm_url}/sessions/{user_id}/{inv}", params={"confirm": "true"})
            if 200 <= d.status_code < 300:
                hit.add(("DELETE", "/sessions/{user_id}/{work_id}"))

        cov = ex.coverage(endpoints, hit)
        return _report(cov, ex_res, st_res, len(tree))


def _report(cov: dict, ex_res: dict, st_res: dict, n_keys: int) -> int:
    bar = "━" * 60
    sc = ex_res["status_counts"]
    api_pct = (cov["hit"] / cov["total"] * 100) if cov["total"] else 0.0
    st_pct = st_res["ratio"] * 100

    print(f"\n{bar}\n  probe verify — 실 CM 블랙박스 게이트\n{bar}")
    print(
        f"(가) CM API 전수 : {cov['hit']}/{cov['total']} ({api_pct:.0f}%)  "
        f"[2xx {sc['2xx']} · 4xx {sc['4xx']}]"
    )
    for e in ex_res["error_results"]:
        print(f"        에러경로 {e}")
    n_present = len(st_res["present"])
    print(
        f"(나) scaffolding : {n_present}/{st_res['total']} "
        f"resource-type ({st_pct:.0f}%) · 저장 키 {n_keys}"
    )

    api_ok = not cov["missing"] and not ex_res["failures"]
    st_ok = st_res["ok"]

    if cov["missing"]:
        print(f"\n✗ 미호출 endpoint ({len(cov['missing'])}):")
        for m in cov["missing"]:
            print(f"  - {m}")
    if ex_res["failures"]:
        print(f"\n✗ API 호출 실패/서버오류 ({len(ex_res['failures'])}):")
        for f in ex_res["failures"]:
            print(f"  - {f}")
    for label, items in (
        ("필수 누락", st_res["missing_required"]),
        ("orphan(설계 밖 키)", st_res["orphans"]),
        ("manifest 불일치", st_res["mismatches"]),
    ):
        if items:
            print(f"\n✗ {label} ({len(items)}):")
            for it in items:
                print(f"  - {it}")

    print(f"\n{bar}")
    print(f"  (가) CM API 전수   : {'✅ PASS' if api_ok else '❌ FAIL'}")
    print(f"  (나) scaffolding   : {'✅ PASS' if st_ok else '❌ FAIL'}")
    print(bar)
    if api_ok and st_ok:
        print("✅ probe verify PASS")
        return 0
    print("❌ probe verify FAIL")
    return 1
