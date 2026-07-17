"""Nexus → DRO 내부 클라이언트 (control + event SSE).

sub-plan ② — Nexus 가 dial (control/event 모두 Nexus→DRO). 인증 없음 (내부망 신뢰, Q32).
- control: POST /control/spawn — 체인 실행 요청 (async 202 ack). user_id 평문 (JWT 아님).
- control: POST /control/output — docx 빌드 (sync 200, C6). IOM→docx→upload→RAW output_ready.
- event: GET /events/{user_id}/{work_id} — per-session raw SSE consume.

SSE 파서는 DRO dispatcher.parse_sse 의 미러 (역방향 — DRO↔Actor 검증된 패턴).
DRO base = settings.DRO_URL (service_url('dro')).
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx
from venezia_contracts.models.dro_api.error import ErrorCode

from .config import settings
from .errors import APIError

log = logging.getLogger(__name__)

_CONTROL_TIMEOUT_S = 10.0
# docx 빌드는 동기 — IOM fetch + python-docx 합성 + CM upload 까지 1 왕복. 넉넉히.
_OUTPUT_TIMEOUT_S = 60.0


async def control_spawn(
    user_id: str,
    work_id: str,
    persona: int,
    pipeline_id: str,
    chain_id: str,
    trigger: dict[str, Any] | None = None,
) -> str:
    """DRO 에 체인 실행 요청. chain_id 는 Nexus 발급 (호출 전 media/turn/conversation 선기록)."""
    body: dict[str, Any] = {
        "user_id": user_id,
        "work_id": work_id,
        "persona": persona,
        "pipeline_id": pipeline_id,
        "chain_id": chain_id,
    }
    if trigger is not None:
        body["trigger"] = trigger
    url = f"{settings.DRO_URL}/control/spawn"
    async with httpx.AsyncClient(timeout=_CONTROL_TIMEOUT_S) as client:
        resp = await client.post(url, json=body)
        resp.raise_for_status()
        data = resp.json()
    return str(data.get("chain_id") or chain_id)


async def control_output(user_id: str, work_id: str, variant: str) -> dict[str, Any]:
    """DRO 에 출원서 docx 빌드 요청 (C6, 동기). DRO 가 IOM→docx→CM upload→RAW output_ready
    까지 수행하고 {document_id, filename, size_bytes} 반환. IOM 미준비(DRO 404)는 client 용
    content_not_ready 로 변환 — build 는 사용자 대면 동기 호출이라 500 으로 새지 않게."""
    body = {"user_id": user_id, "work_id": work_id, "variant": variant}
    url = f"{settings.DRO_URL}/control/output"
    async with httpx.AsyncClient(timeout=_OUTPUT_TIMEOUT_S) as client:
        resp = await client.post(url, json=body)
    if resp.status_code == 404:
        raise APIError(
            ErrorCode.content_not_ready, 404, "작성 콘텐츠 미준비 — 구체화 단계 진행 후 재시도"
        )
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, dict) else {}


def _parse_sse(text_stream: AsyncIterator[str]) -> AsyncIterator[dict[str, Any]]:
    """event/data 한 쌍을 dict 로 yield (dispatcher.parse_sse 미러)."""

    async def _gen() -> AsyncIterator[dict[str, Any]]:
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


async def consume_events(user_id: str, work_id: str) -> AsyncIterator[dict[str, Any]]:
    """DRO per-session SSE 를 열어 raw 이벤트 dict 를 yield. 스트림 종료/에러 시 generator 종료."""
    url = f"{settings.DRO_URL}/events/{user_id}/{work_id}"
    async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10.0)) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()

            async def _line_iter() -> AsyncIterator[str]:
                async for line in resp.aiter_lines():
                    yield line

            async for evt in _parse_sse(_line_iter()):
                # data 에 full raw 이벤트(type/user_id/work_id/persona/seq/payload) 가 실림.
                raw = evt.get("data")
                if isinstance(raw, dict):
                    yield raw
