"""play 의 DRO RAW SSE 소비 — dual 관측의 ② (① = CM trail polling, `_run.py`).

play 내부 self-contained (3i — probe import 아님): 자체 미니 SSE 파서 + httpx streaming.
DRO `GET /events/{user_id}/{work_id}` 는 replay buffer 가 없으므로
구독은 **trigger 전** 시작한다. per-(user,work) 키라 root + spawned 전 chain 을 한 구독이 커버.
서버 generator 는 무한 q.get() — 클라이언트 task cancel 이 유일한 정상 종료.

자동 assert (실패 = play FAIL, 3j "자동검증 가능 = assert"):
  ① ≥1건 수신 ② 전건 `raw-sse-event` schema 통과 ③ seq 수신 순 순단조증가 ④ consumer 무예외.
seq gap / first≠1 은 경고 출력만 (hub queue overflow 시 oldest drop 가능 — 사람 확인 영역).
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx
from rich.console import Console
from venezia_contracts import ContractLoader

_CONTRACT = "raw-sse-event"


@dataclass
class SseCapture:
    """consume_raw_sse 가 채우는 수신 상태 — run_pipeline 이 종료 후 판정에 사용."""

    events: list[dict[str, Any]] = field(default_factory=list)  # 수신 순 raw event
    schema_errors: list[str] = field(default_factory=list)  # "seq=N: <msg>"
    exc: BaseException | None = None  # consumer 비정상 종료 기록 (fail-loud 합류)
    connected: asyncio.Event = field(default_factory=asyncio.Event)


def _parse_sse(text_stream: AsyncIterator[str]) -> AsyncIterator[dict[str, Any]]:
    """event/data 한 쌍을 dict 로 yield — Nexus dro_client._parse_sse 와 동형 (자체 구현)."""

    async def _gen() -> AsyncIterator[dict[str, Any]]:
        import json

        event: str | None = None
        data_lines: list[str] = []
        async for line in text_stream:
            line = line.rstrip("\n")
            if not line:
                if event or data_lines:
                    payload = "\n".join(data_lines)
                    try:
                        data = json.loads(payload) if payload else {}
                    except json.JSONDecodeError:
                        data = {"raw": payload}
                    yield {"type": event or "message", "data": data}
                    event = None
                    data_lines = []
                continue
            if line.startswith("event:"):
                event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].lstrip())

    return _gen()


async def consume_raw_sse(dro_url: str, user_id: str, work_id: str, cap: SseCapture) -> None:
    """DRO per-session SSE 구독 — 수신 즉시 schema 검증 후 cap 에 누적.

    예외는 cap.exc 에 기록하고 조용히 종료 (본 trail-polling 흐름 비파괴 —
    report_sse 가 FAIL 로 합류시켜 fail-loud). CancelledError 는 정상 종료 경로.
    """
    loader = ContractLoader()
    url = f"{dro_url.rstrip('/')}/events/{user_id}/{work_id}"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10.0)) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                cap.connected.set()

                async def _line_iter() -> AsyncIterator[str]:
                    async for line in resp.aiter_lines():
                        yield line

                async for evt in _parse_sse(_line_iter()):
                    raw = evt.get("data")
                    if not isinstance(raw, dict):
                        cap.schema_errors.append(f"non-dict SSE data: {raw!r}")
                        continue
                    result = loader.validate(_CONTRACT, raw)
                    if not result:
                        cap.schema_errors.append(
                            f"seq={raw.get('seq')}: " + "; ".join(result.errors)
                        )
                    cap.events.append(raw)
    except asyncio.CancelledError:
        raise
    except BaseException as e:  # noqa: BLE001 — report_sse 에서 FAIL 합류 (fail-loud)
        cap.exc = e


async def drain_sse(cap: SseCapture, expected_chains: int, grace: float = 5.0) -> None:
    """전 chain 의 종료 이벤트가 SSE 로 도착할 시간을 준다.

    CM 의 chain status:done patch 가 chain_completed emit 보다 선행하므로
    _poll_chain_done 리턴 시점엔 마지막 이벤트가 미도착일 수 있다. 실패 chain 은
    chain_completed 대신 error 를 발행하므로 둘의 합으로 센다. grace 초과 시 탈출.
    """
    deadline = asyncio.get_event_loop().time() + grace
    while asyncio.get_event_loop().time() < deadline:
        done = sum(1 for e in cap.events if e.get("type") in ("chain_completed", "error"))
        if done >= expected_chains:
            return
        await asyncio.sleep(0.2)


def report_sse(cap: SseCapture, chains_traced: int, console: Console) -> bool:
    """SSE 수신 요약 출력 + 자동 assert 4종. False = play FAIL 합류."""
    total = len(cap.events)
    hist = Counter(e.get("type") or "?" for e in cap.events)
    seqs: list[int] = [s for e in cap.events if isinstance(s := e.get("seq"), int)]
    monotonic = all(b > a for a, b in zip(seqs, seqs[1:], strict=False))
    completed = hist.get("chain_completed", 0) + hist.get("error", 0)

    console.print(f"  Events received : [bold]{total}[/]")
    if hist:
        console.print(
            "  By type         : " + " · ".join(f"{t} {n}" for t, n in sorted(hist.items()))
        )
    if seqs:
        gaps = sum(1 for a, b in zip(seqs, seqs[1:], strict=False) if b != a + 1)
        console.print(f"  Seq range       : {seqs[0]}..{seqs[-1]}  (gaps={gaps})")
        if seqs[0] != 1 or gaps:
            console.print("  [yellow]⚠ seq first≠1 또는 gap — hub drop 가능성 (경고만)[/]")
    console.print(f"  Chain end events: {completed} (traced {chains_traced})")

    ok = True
    if total < 1:
        console.print("  [red]✗ SSE 이벤트 0건 수신 — consumer 배선/DRO emit 확인[/]")
        ok = False
    if cap.schema_errors:
        console.print(f"  [red]✗ schema 위반 {len(cap.schema_errors)}건 (raw-sse-event):[/]")
        for msg in cap.schema_errors[:5]:
            console.print(f"      [red]{msg[:160]}[/]")
        ok = False
    if seqs and not monotonic:
        console.print("  [red]✗ seq 비단조 — 수신 순서 위반[/]")
        ok = False
    if cap.exc is not None:
        console.print(f"  [red]✗ SSE consumer 예외: {type(cap.exc).__name__}: {cap.exc}[/]")
        ok = False
    if ok:
        console.print(f"  [green]✓ raw SSE: {total}건 전건 schema 통과 + seq 단조[/]")
    return ok
