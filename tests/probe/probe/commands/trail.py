"""probe trail — chain 의 trail.jsonl 만 stream 출력."""

from __future__ import annotations

import json

import httpx

from .._common import CM_URL


async def run_trail(
    chain_id: str,
    user_id: str,
    work_id: str,
    cm_url: str = CM_URL,
) -> int:
    """CM 의 chains/{chain_id}/trail 호출, 각 줄 한 event 씩 표시."""
    async with httpx.AsyncClient(timeout=30) as http:
        url = f"{cm_url}/sessions/{user_id}/{work_id}/chains/{chain_id}/trail"
        r = await http.get(url, timeout=10)
        if r.status_code != 200:
            print(f"❌ trail fetch failed: {r.status_code} {r.text[:200]}")
            return 1
        for line in r.text.splitlines():
            if not line.strip():
                continue
            try:
                evt = json.loads(line)
                ts = evt.get("timestamp", "")
                event = evt.get("event", "?")
                rt = evt.get("rt_id", "")[:30]
                step = evt.get("step_id", "")
                print(f"  {ts}  {event:<22}  rt={rt:<32}  step={step}")
            except json.JSONDecodeError:
                print(f"  ! {line[:160]}")
        return 0
