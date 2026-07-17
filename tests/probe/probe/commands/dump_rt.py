"""probe dump-rt — chain 의 특정 RT JSON export (debugging)."""

from __future__ import annotations

import json

import httpx

from .._common import CM_URL


async def run_dump_rt(
    user_id: str,
    work_id: str,
    chain_id: str,
    rt_id: str,
    cm_url: str = CM_URL,
) -> int:
    """GET /sessions/{u}/{i}/chains/{c}/rts/{rt} → RT JSON stdout."""
    async with httpx.AsyncClient(timeout=10) as http:
        url = f"{cm_url}/sessions/{user_id}/{work_id}/chains/{chain_id}/rts/{rt_id}"
        r = await http.get(url)
        if r.status_code != 200:
            print(f"❌ dump-rt failed: {r.status_code} {r.text[:200]}")
            return 1
        rt = r.json()
        print(json.dumps(rt, indent=2, ensure_ascii=False))
        return 0
