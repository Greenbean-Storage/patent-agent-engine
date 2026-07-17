"""probe structure — 세션의 실제 S3 메모리 구조를 scaffolding + manifest 와 대조 검증.

CM 에서 (1) 실제 저장 키 전수(tree), (2) manifest 4종(runtime/models/outputs/context) 을 받아
probe._structure.verify_structure 로 검증:
  - orphan          : scaffolding 밖 키 (설계에 없는 파일)
  - missing_required : 필수 resource-type(context/runtime manifest) 부재
  - mismatch        : manifest↔실제 불일치 (runtime chains / outputs 산출물)
  - 관찰 비율 ≥ 99% : scaffolding 전 resource-type(drawings 포함, users 제외) 관찰

검증 로직은 probe._structure (제품/shared 엔 검증 로직 0). 이 명령은 그 로직을 live CM 에
물려 돌리는 얇은 glue + 리포트.
"""

from __future__ import annotations

import httpx

from .._common import CM_URL
from .._structure import verify_structure


async def _get_json(http: httpx.AsyncClient, url: str):
    try:
        r = await http.get(url)
    except Exception:  # noqa: BLE001
        return None
    return r.json() if r.status_code == 200 else None


async def run_structure(user_id: str, work_id: str, cm_url: str = CM_URL) -> int:
    base = f"{cm_url}/sessions/{user_id}/{work_id}"
    async with httpx.AsyncClient(timeout=15) as http:
        tree_r = await http.get(f"{base}/tree")
        if tree_r.status_code != 200:
            print(f"✗ tree fetch 실패 (status={tree_r.status_code}) — 세션이 없거나 CM 미가동")
            return 1
        keys: list[str] = tree_r.json().get("keys", [])
        # manifest 4종 — runtime/outputs 는 교차검증 입력, models/context 는 가독 확인(존재).
        runtime_manifest = await _get_json(http, f"{base}/runtime")
        outputs_manifest = await _get_json(http, f"{base}/outputs/manifest")
        models_manifest = await _get_json(http, f"{base}/models/manifest")
        context_manifest = await _get_json(http, f"{base}/manifest/context")

    report = verify_structure(keys, runtime_manifest, outputs_manifest)
    _print_report(user_id, work_id, keys, report, models_manifest, context_manifest)
    return 0 if report["ok"] else 1


def _print_report(
    user_id: str,
    work_id: str,
    keys: list[str],
    report: dict,
    models_manifest: dict | None,
    context_manifest: dict | None,
) -> None:
    print(f"User:      {user_id}")
    print(f"Invention: {work_id}")
    print(f"Stored keys: {len(keys)}")
    print(
        f"manifest 가독: context={context_manifest is not None} models={models_manifest is not None}"
    )
    print()
    present = report["present"]
    total = report["total"]
    pct = report["ratio"] * 100
    print(f"관찰된 resource-type: {len(present)}/{total}  ({pct:.0f}%)")
    for rtype in present:
        print(f"  ✓ {rtype}")

    for label, items in (
        ("필수 누락", report["missing_required"]),
        ("orphan — scaffolding 밖 키", report["orphans"]),
        ("manifest 불일치", report["mismatches"]),
    ):
        if items:
            print(f"\n✗ {label} ({len(items)}):")
            for it in items:
                print(f"  - {it}")

    print()
    print("✅ 구조 정합" if report["ok"] else "❌ 구조 불일치 — 위 항목 확인")
