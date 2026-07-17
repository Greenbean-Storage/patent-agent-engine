"""probe list-chains — invention 의 chain 인벤토리 (lightweight)."""

from __future__ import annotations

import httpx

from .._common import CM_URL


async def run_list_chains(
    user_id: str,
    work_id: str,
    cm_url: str = CM_URL,
) -> int:
    """GET /sessions/{u}/{i}/runtime → chain entry list 표시 (CM 의 chain 인덱스 라우트)."""
    async with httpx.AsyncClient(timeout=10) as http:
        r = await http.get(f"{cm_url}/sessions/{user_id}/{work_id}/runtime")
        if r.status_code != 200:
            print(f"❌ list-chains fetch failed: {r.status_code} {r.text[:200]}")
            return 1
        body = r.json() or {}
        chains = body.get("chains") or []
        print(f"User:      {user_id}")
        print(f"Invention: {work_id}")
        print(f"Chains:    {len(chains)}")
        for c in chains:
            cid = c.get("chain_id", "?")
            pid = c.get("pipeline_id", "?")
            persona = c.get("persona", "?")
            status = c.get("status", "?")
            started = c.get("started_at", "?")
            try:
                p_str = f"P{int(persona):02d}"
            except (ValueError, TypeError):
                p_str = f"P{persona}"
            print(f"  • {cid}  [{p_str}]  {pid:<40}  {status:<10}  {started}")
        return 0
