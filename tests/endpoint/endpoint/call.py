"""endpoint 단건 호출 UI — 탐색/디버그용 (검증 게이트 아님).

  make endpoint call REST="GET /api/v1/info/providers" [BODY='{"k":"v"}']
  make endpoint call WS='message.send {"content":"안녕하세요"}'   # correlation_id 자동 주입

REST: Nexus 에 1회 요청 → status + body pretty 출력. exit 0 = 응답 수신 (status 무관).
WS:  fresh work 생성 → thread/stream 연결 → action 1건 송신 → 수신 이벤트를
     quiet-drain(3s 무이벤트 종료, cap 30s)으로 출력. exit 0 = 송신 성공.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid

import httpx
import websockets

from venezia_topology import service_url

_QUIET_S = 3.0
_CAP_S = 30.0


def _nexus() -> str:
    return service_url("nexus")


async def _call_rest(rest: str, body: str | None) -> int:
    parts = rest.split(None, 1)
    if len(parts) != 2:
        print(f'✗ REST 형식: "METHOD /path" (받음: {rest!r})')
        return 2
    method, path = parts[0].upper(), parts[1]
    payload = json.loads(body) if body else None
    async with httpx.AsyncClient(timeout=30.0) as http:
        r = await http.request(method, f"{_nexus()}{path}", json=payload)
    print(f"{method} {path} → {r.status_code}")
    try:
        print(json.dumps(r.json(), ensure_ascii=False, indent=2))
    except ValueError:
        print(r.text[:2000])
    return 0


async def _call_ws(ws_arg: str, body: str | None) -> int:
    parts = ws_arg.split(None, 1)
    action = parts[0]
    data = json.loads(parts[1]) if len(parts) > 1 else (json.loads(body) if body else {})
    if action == "message.send" and "correlation_id" not in data:
        data["correlation_id"] = uuid.uuid4().hex  # 멱등키 — 디버그 편의상 자동 부여
    async with httpx.AsyncClient(timeout=30.0) as http:
        r = await http.post(f"{_nexus()}/api/v1/user/works")
        r.raise_for_status()
        wid = r.json()["work_id"]
    print(f"work_id={wid}")
    ws_url = _nexus().replace("http", "ws") + f"/api/v1/works/{wid}/thread/stream"
    async with websockets.connect(ws_url) as ws:
        await ws.send(json.dumps({"action": action, "data": data}))
        print(f"→ {action} {json.dumps(data, ensure_ascii=False)[:200]}")
        loop = asyncio.get_event_loop()
        t0 = loop.time()
        last = t0
        while loop.time() - t0 < _CAP_S and loop.time() - last < _QUIET_S:
            with contextlib.suppress(TimeoutError, asyncio.TimeoutError):
                evt = json.loads(await asyncio.wait_for(ws.recv(), timeout=_QUIET_S))
                last = loop.time()
                summary = json.dumps(evt.get("data") or {}, ensure_ascii=False)
                print(f"← seq={evt.get('seq')} {evt.get('type')}  {summary[:160]}")
    return 0


def run_call(rest: str | None, ws_arg: str | None, body: str | None) -> int:
    if rest:
        return asyncio.run(_call_rest(rest, body))
    if ws_arg:
        return asyncio.run(_call_ws(ws_arg, body))
    print("✗ 사용법: make endpoint call REST=\"GET /path\" | WS='<action> {json}' [BODY=...]")
    return 2
