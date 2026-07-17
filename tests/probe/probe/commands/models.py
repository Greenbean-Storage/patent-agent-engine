"""probe models — invention 의 4 모델 (IOM/CMM/CDS/UR) dump.

P-A v1 의 contexts/ namespace 가 P-A v3 에서 models/ + 페르소나 dialog 로 분리됨.
- IOM (invention-object-model) — P02 director 가 write
- CMM (concept-maturity-model) — P02 maturity.compute tool
- CDS (concept-discovery-stack)  — P02 staging.save tool
- UR  (user-roadmap)             — P02 roadmap.persist tool (top-level array)

`--pointer` 옵션은 RFC 6901 JSON Pointer 로 server-side 부분 read (예: `--pointer /fields/title`).
"""

from __future__ import annotations

import json

import httpx

from .._common import CM_URL

_MODELS = (
    ("invention-object-model", "IOM"),
    ("concept-maturity-model", "CMM"),
    ("concept-discovery-stack", "CDS"),
    ("user-roadmap", "UR"),
)


async def run_models(
    user_id: str,
    work_id: str,
    cm_url: str = CM_URL,
    pointer: str = "",
    only: str | None = None,
) -> int:
    """models/ 의 4 모델 GET. `only` 지정 시 그 모델만, pointer 지정 시 부분 read."""
    async with httpx.AsyncClient(timeout=10) as http:
        print(f"User:      {user_id}")
        print(f"Invention: {work_id}")
        if pointer:
            print(f"Pointer:   {pointer}")
        print()
        for slug, label in _MODELS:
            if only and only != slug:
                continue
            url = f"{cm_url}/sessions/{user_id}/{work_id}/models/{slug}"
            params = {"pointer": pointer} if pointer else None
            try:
                r = await http.get(url, params=params)
            except Exception as e:  # noqa: BLE001
                print(f"  ✗ {label:<4}  error: {e}")
                continue
            if r.status_code == 404:
                print(f"  ─ {label:<4}  (none)")
                continue
            if r.status_code == 400:
                print(f"  ✗ {label:<4}  bad pointer: {r.text[:200]}")
                continue
            if r.status_code != 200:
                print(f"  ✗ {label:<4}  status={r.status_code}")
                continue
            data = r.json()
            size = len(json.dumps(data, ensure_ascii=False))
            preview = json.dumps(data, ensure_ascii=False)[:120]
            if len(preview) >= 120:
                preview += "…"
            print(f"  ✓ {label:<4}  {size:>6} chars  {preview}")
        return 0
