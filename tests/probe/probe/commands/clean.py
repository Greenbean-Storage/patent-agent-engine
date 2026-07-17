"""probe clean — invention 삭제 (CM DELETE endpoint 호출).

DELETE /sessions/{user_id}/{work_id}?confirm=true → S3 prefix 의 모든 object 삭제.
되돌릴 수 없음 — CLI 가 사용자에게 confirm 요구 (--yes 옵션 없으면 prompt).
"""

from __future__ import annotations

import sys

import httpx

from .._common import CM_URL


async def run_clean(
    user_id: str,
    work_id: str,
    *,
    yes: bool = False,
    cm_url: str = CM_URL,
) -> int:
    """DELETE invention. yes=False 면 stdin prompt 로 confirm 요구."""
    if not yes:
        print(f"WARNING: 되돌릴 수 없는 삭제. user={user_id} invention={work_id}")
        try:
            ans = input("정말 삭제? 'yes' 입력: ").strip().lower()
        except EOFError:
            ans = ""
        if ans != "yes":
            print("취소됨.")
            return 1

    async with httpx.AsyncClient(timeout=60) as http:
        url = f"{cm_url}/sessions/{user_id}/{work_id}?confirm=true"
        r = await http.delete(url)
        if r.status_code != 200:
            print(f"❌ clean failed: {r.status_code} {r.text[:200]}", file=sys.stderr)
            return 1
        body = r.json() or {}
        deleted = body.get("deleted_objects", 0)
        print(f"✓ deleted {deleted} S3 objects (user={user_id}, invention={work_id})")
        return 0
