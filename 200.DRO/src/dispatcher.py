"""Actor /dispatch 호출 + SSE 응답 소비 + 우선순위 순 fallback."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx

from .config import settings

log = logging.getLogger(__name__)


class ActorError(Exception):
    pass


class AllActorsBusy(Exception):
    pass


def parse_sse(text_stream: AsyncIterator[str]) -> AsyncIterator[dict[str, Any]]:
    """순수 비동기 SSE 파서. event/data 한 쌍을 dict 로 yield."""

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


async def dispatch_to_actor(
    persona: int,
    chain_id: str,
    rt_id: str,
    user_id: str,
    work_id: str,
    on_event: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """unified 단일 actor 직결 (구 persona 후보 풀/fallback 폐기 — B-3).

    503(persona 슬롯 포화) → AllActorsBusy (dispatch_with_retry 의 시간예산 backoff 가 처리).
    4xx/5xx·연결 실패 → ActorError (즉시 실패).
    """
    body = {
        "chain_id": chain_id,
        "rt_id": rt_id,
        "user_id": user_id,
        "work_id": work_id,
        "persona": persona,  # Actor 가 persona sub-folder 직접 read (brute-force 폐기, 3a)
    }

    target = settings.ACTOR_URL
    url = f"{target.rstrip('/')}/dispatch"
    try:
        async with httpx.AsyncClient(timeout=settings.DISPATCH_TIMEOUT_S) as client:
            async with client.stream("POST", url, json=body) as resp:
                if resp.status_code == 503:
                    raise AllActorsBusy(f"actor busy (persona {persona} slot saturated)")
                if resp.status_code >= 400:
                    text = (await resp.aread()).decode("utf-8", errors="replace")
                    raise ActorError(f"actor {target} {resp.status_code}: {text[:200]}")

                final_result: dict[str, Any] | None = None
                error_payload: dict[str, Any] | None = None

                async def _line_iter() -> AsyncIterator[str]:
                    async for line in resp.aiter_lines():
                        yield line

                async for evt in parse_sse(_line_iter()):
                    if on_event is not None:
                        try:
                            await on_event(evt)
                        except Exception:  # noqa: BLE001
                            log.exception("on_event handler failed")
                    if evt["type"] == "result":
                        final_result = evt["data"]
                    elif evt["type"] == "error":
                        error_payload = evt["data"]

                if error_payload is not None:
                    # Actor 에러 = ErrorEnvelope {"error":{"code","message"}}
                    msg = (
                        (error_payload.get("error") or {}).get("message")
                        or error_payload.get("message")
                        or "actor reported error"
                    )
                    raise ActorError(msg)
                if final_result is None:
                    raise ActorError("actor stream ended without result")
                return final_result
    except (httpx.RequestError, httpx.TimeoutException) as e:
        raise ActorError(f"actor dispatch failed ({target}): {e}") from e


async def dispatch_tool(
    tool_name: str,
    params: dict[str, Any],
    *,
    user_id: str | None = None,
    work_id: str | None = None,
    chain_id: str | None = None,
    persona: int | None = None,
    step_id: str | None = None,
    rt_id: str | None = None,
    timeout: float = 60.0,
    backoff: float | None = None,
    budget_s: float | None = None,
) -> dict[str, Any]:
    """Actor `POST /tool/{tool_name}` 호출. tool=RT 통일(N-7) — DRO 가 chain_id/persona/
    step_id/rt_id 를 전달하면 Actor 가 tool 출력을 그 RT 레코드(rts/{rt_id}.json)에 기록.

    unified 단일 actor 직결 (구 persona_hint/후보 풀 폐기 — B-3). 503(tool 풀 포화)이면
    **시간예산(budget_s) 안에서 지수 backoff (상한 BUSY_BACKOFF_MAX_S) 재시도 지속 —
    포화 ≠ 실패 (B-1, 횟수 상한 폐기)**. 4xx/5xx·연결 실패는 즉시 ActorError.
    """
    target = settings.ACTOR_URL
    url = f"{target.rstrip('/')}/tool/{tool_name}"
    body: dict[str, Any] = {"params": params}
    for k, v in (
        ("user_id", user_id),
        ("work_id", work_id),
        ("chain_id", chain_id),
        ("persona", persona),
        ("step_id", step_id),
        ("rt_id", rt_id),
    ):
        if v is not None:
            body[k] = v
    bo = backoff if backoff is not None else settings.BUSY_BACKOFF_S
    budget = budget_s if budget_s is not None else settings.DISPATCH_RETRY_BUDGET_S
    deadline = asyncio.get_running_loop().time() + budget
    attempt = 0

    while True:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=body)
        except httpx.RequestError as e:
            raise ActorError(f"tool {tool_name} request failed ({target}): {e}") from e
        if resp.status_code == 503:
            delay = min(bo * (2**attempt), settings.BUSY_BACKOFF_MAX_S)
            if asyncio.get_running_loop().time() + delay > deadline:
                raise AllActorsBusy(f"actor busy for tool {tool_name} (시간예산 소진)")
            log.info("actor tool busy — backoff %.1fs: %s", delay, target)
            attempt += 1
            await asyncio.sleep(delay)
            continue
        if resp.status_code == 404:
            raise ActorError(f"tool not registered on {target}: {tool_name}")
        if resp.status_code >= 400:
            text = resp.text
            raise ActorError(
                f"tool {tool_name} on {target} returned {resp.status_code}: {text[:300]}"
            )
        try:
            return resp.json()
        except Exception:
            return {"status": "success", "result": resp.text}


async def dispatch_with_retry(
    persona: int,
    chain_id: str,
    rt_id: str,
    user_id: str,
    work_id: str,
    on_event: Callable[..., Any] | None = None,
    backoff: float | None = None,
    budget_s: float | None = None,
) -> dict[str, Any]:
    """AllActorsBusy(포화) 시 시간예산 안에서 지수 backoff 재시도 — 포화 ≠ 실패 (B-1).

    횟수 상한(구 max_attempts=3) 폐기 — budget_s (default DISPATCH_RETRY_BUDGET_S) 가
    소진될 때까지 재시도 지속 (delay 상한 = BUSY_BACKOFF_MAX_S). 영구 에러(ActorError)는
    즉시 raise.
    """
    bo = backoff if backoff is not None else settings.BUSY_BACKOFF_S
    budget = budget_s if budget_s is not None else settings.DISPATCH_RETRY_BUDGET_S
    deadline = asyncio.get_running_loop().time() + budget
    attempt = 0
    while True:
        try:
            return await dispatch_to_actor(
                persona, chain_id, rt_id, user_id, work_id, on_event=on_event
            )
        except AllActorsBusy:
            delay = min(bo * (2**attempt), settings.BUSY_BACKOFF_MAX_S)
            if asyncio.get_running_loop().time() + delay > deadline:
                raise  # 시간예산 소진
            attempt += 1
            await asyncio.sleep(delay)
