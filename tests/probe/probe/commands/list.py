"""probe list — 사용자의 세션·chain 목록.

invention title 은 IOM 의 `/bibliographic/title/ko` 를 RFC 6901 server-side pointer
로 부분 fetch (전체 IOM 대신 title 만). IOM 없으면 `(no IOM)`.
"""

from __future__ import annotations

import asyncio

import httpx

from .._common import CM_URL, dev_token


async def _fetch_title(http: httpx.AsyncClient, cm_url: str, user_id: str, iid: str) -> str:
    url = f"{cm_url}/sessions/{user_id}/{iid}/models/invention-object-model"
    try:
        r = await http.get(url, params={"pointer": "/bibliographic/title/ko"}, timeout=5)
    except Exception:  # noqa: BLE001
        return "(fetch error)"
    if r.status_code == 404:
        return "(no IOM)"
    if r.status_code == 200:
        title = r.text.strip().strip('"')
        return title or "(empty title)"
    return f"(status {r.status_code})"


async def run_list(
    user_id: str | None,
    cm_url: str = CM_URL,
) -> int:
    """CM 의 /sessions/{user_id} 호출, invention 별 IOM title (pointer fetch) 표시."""
    async with httpx.AsyncClient(timeout=30) as http:
        if not user_id:
            _token, user_id = await dev_token(http)
        r = await http.get(f"{cm_url}/sessions/{user_id}", timeout=10)
        if r.status_code != 200:
            print(f"❌ list fetch failed: {r.status_code} {r.text[:200]}")
            return 1
        body = r.json() or {}
        invs = body.get("inventions") or []
        print(f"User: {user_id}")
        print(f"Inventions: {len(invs)}")
        # title pointer fetch 를 invention 별 병렬화
        iids = [inv.get("work_id", "?") for inv in invs]
        titles = await asyncio.gather(*(_fetch_title(http, cm_url, user_id, iid) for iid in iids))
        for iid, title in zip(iids, titles, strict=True):
            print(f"  • {iid}  —  {title}")
        return 0
