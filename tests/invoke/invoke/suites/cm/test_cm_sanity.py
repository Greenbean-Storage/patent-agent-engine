"""conftest 하니스 sanity — stub S3 + ASGITransport + paginator 동작 확인.

(전수 커버는 test_cm_router_*.py / test_cm_store*.py 가 담당.)
"""

from __future__ import annotations

import asyncio


def test_create_session_and_list(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.post("/sessions", json={"user_id": "u-1"})
            assert r.status_code == 201
            iid = r.json()["work_id"]
            # paginator (CommonPrefixes) 경유 list
            r2 = await c.get("/sessions/u-1")
            assert r2.status_code == 200
            ids = [x["work_id"] for x in r2.json()["inventions"]]
            assert iid in ids

    asyncio.run(_run())
