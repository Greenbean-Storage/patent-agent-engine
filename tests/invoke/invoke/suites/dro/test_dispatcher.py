"""200.DRO dispatcher — SSE parser + dispatch_to_actor / dispatch_tool / dispatch_with_retry.

전략: MockTransport 로 SSE 스트림 / status code 를 재현. dispatcher.httpx.AsyncClient 를
MockTransport 주입 팩토리로 monkeypatch. settings.ACTOR_URL(unified 단일 actor 직결) 과
asyncio.sleep 도 patch. 실제 분기(503 AllActorsBusy / 4xx ActorError / error event /
no-result / RequestError 즉시 실패 / busy 시간예산 backoff)를 진짜 assert.

async 는 asyncio.run(...) 로 (pytest-asyncio mark 없이; 기존 suite 패턴).
parse_sse 테스트는 이 파일에 이미 있으므로 중복하지 않는다.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "200.DRO"))

from src import dispatcher as D  # noqa: E402
from src.dispatcher import (  # noqa: E402
    ActorError,
    AllActorsBusy,
    dispatch_to_actor,
    dispatch_tool,
    dispatch_with_retry,
    parse_sse,
)


def test_dispatcher_sse_parser():
    raw = (
        'event: started\ndata: {"rt_id":"rt_a"}\n\n'
        'event: progress\ndata: {"phase":"llm"}\n\n'
        'event: result\ndata: {"text":"hello"}\n\n'
    )

    async def _lines():
        for line in raw.splitlines():
            yield line

    async def _main():
        return [evt async for evt in parse_sse(_lines())]

    out = asyncio.run(_main())
    assert [e["type"] for e in out] == ["started", "progress", "result"]
    assert out[2]["data"] == {"text": "hello"}


# ── 공통 헬퍼 ───────────────────────────────────────────────────────────────


def _patch_client(monkeypatch, handler) -> None:
    """dispatcher 가 쓰는 httpx.AsyncClient 를 MockTransport 주입 팩토리로 교체."""
    # 실제 생성자를 먼저 잡아둔다 (patch 후 httpx.AsyncClient 는 _factory 자신).
    real_cls = httpx.AsyncClient

    def _factory(**kw: Any) -> httpx.AsyncClient:
        kw.pop("transport", None)
        return real_cls(transport=httpx.MockTransport(handler), **kw)

    monkeypatch.setattr(D.httpx, "AsyncClient", _factory)


def _patch_actor_url(monkeypatch, url: str = "http://actor:59300") -> None:
    """unified 단일 actor URL 교체 — settings.ACTOR_URL 은 property 라 클래스 단위 patch."""
    monkeypatch.setattr(type(D.settings), "ACTOR_URL", property(lambda self: url))


def _no_sleep(monkeypatch) -> list[float]:
    """asyncio.sleep 를 즉시 반환으로 교체 + 호출 인자 기록."""
    slept: list[float] = []

    async def _fake(delay: float) -> None:
        slept.append(delay)

    monkeypatch.setattr(D.asyncio, "sleep", _fake)
    return slept


def _fake_clock(monkeypatch) -> list[float]:
    """가상 시계 — sleep 이 시간을 전진시켜 시간예산(deadline) 의미론을 결정적으로 검증.

    dispatcher 의 deadline 계산(asyncio.get_running_loop().time())과 sleep 을 함께 교체.
    """
    state = {"t": 0.0}
    slept: list[float] = []

    class _Loop:
        def time(self) -> float:
            return state["t"]

    async def _fake(delay: float) -> None:
        slept.append(delay)
        state["t"] += delay

    monkeypatch.setattr(D.asyncio, "get_running_loop", lambda: _Loop())
    monkeypatch.setattr(D.asyncio, "sleep", _fake)
    return slept


def _sse(*events: tuple[str, str]) -> bytes:
    return ("".join(f"event: {e}\ndata: {d}\n\n" for e, d in events)).encode()


# ── parse_sse 추가 분기 (JSONDecodeError → raw, event 없는 data, trailing 미완결) ──


def test_parse_sse_invalid_json_and_message_default():
    raw = 'data: not-json\n\ndata: {"ok":1}\n\n'

    async def _lines():
        for line in raw.splitlines():
            yield line

    out = asyncio.run(_collect(parse_sse(_lines())))
    # event 라인 없으면 type 은 "message" default. invalid JSON 은 {"raw": payload}.
    assert out[0] == {"type": "message", "data": {"raw": "not-json"}}
    assert out[1] == {"type": "message", "data": {"ok": 1}}


def test_parse_sse_empty_data_yields_empty_dict():
    raw = "event: ping\n\n"

    async def _lines():
        for line in raw.splitlines():
            yield line

    out = asyncio.run(_collect(parse_sse(_lines())))
    assert out == [{"type": "ping", "data": {}}]


async def _collect(agen) -> list[dict[str, Any]]:
    return [evt async for evt in agen]


# ── dispatch_to_actor ────────────────────────────────────────────────────────


def test_dispatch_to_actor_success_and_on_event(monkeypatch):
    _patch_actor_url(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "actor"
        assert request.url.path == "/dispatch"
        import json as _json

        body = _json.loads(request.content)
        assert body == {
            "chain_id": "c1",
            "rt_id": "rt1",
            "user_id": "u1",
            "work_id": "inv1",
            "persona": 2,
        }
        return httpx.Response(
            200,
            content=_sse(
                ("started", '{"rt_id":"rt1"}'),
                ("result", '{"text":"done"}'),
            ),
        )

    _patch_client(monkeypatch, handler)

    seen: list[dict[str, Any]] = []

    async def _on_event(evt: dict[str, Any]) -> None:
        seen.append(evt)

    out = asyncio.run(dispatch_to_actor(2, "c1", "rt1", "u1", "inv1", on_event=_on_event))
    assert out == {"text": "done"}
    assert [e["type"] for e in seen] == ["started", "result"]


def test_dispatch_to_actor_on_event_exception_swallowed(monkeypatch):
    """on_event 가 raise 해도 dispatch 는 계속 진행 (log.exception 만)."""
    _patch_actor_url(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse(("result", '{"ok":true}')))

    _patch_client(monkeypatch, handler)

    async def _boom(evt: dict[str, Any]) -> None:
        raise RuntimeError("handler blew up")

    out = asyncio.run(dispatch_to_actor(2, "c", "rt", "u", "inv", on_event=_boom))
    assert out == {"ok": True}


def test_dispatch_to_actor_503_raises_all_busy(monkeypatch):
    """unified 단일 actor — 503(persona 슬롯 포화)은 즉시 AllActorsBusy
    (재시도는 dispatch_with_retry 의 시간예산 backoff 몫, 구 후보 fallback 폐기)."""
    _patch_actor_url(monkeypatch)
    _patch_client(monkeypatch, lambda req: httpx.Response(503))
    with pytest.raises(AllActorsBusy, match="persona 2 slot saturated"):
        asyncio.run(dispatch_to_actor(2, "c", "rt", "u", "inv"))


def test_dispatch_to_actor_4xx_raises_actor_error(monkeypatch):
    _patch_actor_url(monkeypatch)
    _patch_client(
        monkeypatch,
        lambda req: httpx.Response(400, content=b"bad request body here"),
    )
    with pytest.raises(ActorError, match="400: bad request body here"):
        asyncio.run(dispatch_to_actor(2, "c", "rt", "u", "inv"))


def test_dispatch_to_actor_error_event_raises(monkeypatch):
    _patch_actor_url(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        # Actor 에러 = ErrorEnvelope {"error":{"code","message"}}
        return httpx.Response(
            200, content=_sse(("error", '{"error":{"code":"internal","message":"actor exploded"}}'))
        )

    _patch_client(monkeypatch, handler)
    with pytest.raises(ActorError, match="actor exploded"):
        asyncio.run(dispatch_to_actor(2, "c", "rt", "u", "inv"))


def test_dispatch_to_actor_error_event_without_message(monkeypatch):
    """error event 에 message 없으면 default 문구."""
    _patch_actor_url(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse(("error", '{"code":"X"}')))

    _patch_client(monkeypatch, handler)
    with pytest.raises(ActorError, match="actor reported error"):
        asyncio.run(dispatch_to_actor(2, "c", "rt", "u", "inv"))


def test_dispatch_to_actor_stream_no_result_raises(monkeypatch):
    _patch_actor_url(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse(("progress", '{"phase":"llm"}')))

    _patch_client(monkeypatch, handler)
    with pytest.raises(ActorError, match="ended without result"):
        asyncio.run(dispatch_to_actor(2, "c", "rt", "u", "inv"))


def test_dispatch_to_actor_request_error_raises_immediately(monkeypatch):
    """연결 실패 = 즉시 ActorError — 단일 대상이라 '다음 후보' 없음 (영구 에러 즉시 실패)."""
    _patch_actor_url(monkeypatch, "http://dead:59300")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("conn refused", request=request)

    _patch_client(monkeypatch, handler)
    with pytest.raises(ActorError, match="actor dispatch failed"):
        asyncio.run(dispatch_to_actor(2, "c", "rt", "u", "inv"))


# ── dispatch_tool ────────────────────────────────────────────────────────────


def test_dispatch_tool_success_json_body(monkeypatch):
    """unified 단일 actor 직결 — path/body 전달 + JSON 반환."""
    _patch_actor_url(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "actor"
        assert request.url.path == "/tool/kipris.search_patents"
        import json as _json

        assert _json.loads(request.content) == {"params": {"q": "battery"}}
        return httpx.Response(200, json={"hits": 3})

    _patch_client(monkeypatch, handler)
    out = asyncio.run(dispatch_tool("kipris.search_patents", {"q": "battery"}))
    assert out == {"hits": 3}


def test_dispatch_tool_includes_rt_identifiers(monkeypatch):
    """tool=RT 통일(N-7) — rt 식별자 전달 시 body 에 포함 (Actor 가 그 RT 에 출력 기록)."""
    _patch_actor_url(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        assert _json.loads(request.content) == {
            "params": {"q": "x"},
            "user_id": "u",
            "work_id": "inv",
            "chain_id": "c1",
            "persona": 2,
            "step_id": "t0",
            "rt_id": "rt9",
        }
        return httpx.Response(200, json={"ok": True})

    _patch_client(monkeypatch, handler)
    out = asyncio.run(
        dispatch_tool(
            "maturity.compute",
            {"q": "x"},
            user_id="u",
            work_id="inv",
            chain_id="c1",
            persona=2,
            step_id="t0",
            rt_id="rt9",
        )
    )
    assert out == {"ok": True}


def test_dispatch_tool_404_raises_not_registered(monkeypatch):
    _patch_actor_url(monkeypatch)
    _patch_client(monkeypatch, lambda req: httpx.Response(404))
    with pytest.raises(ActorError, match="tool not registered on .*: t.x"):
        asyncio.run(dispatch_tool("t.x", {}))


def test_dispatch_tool_500_raises_with_body(monkeypatch):
    _patch_actor_url(monkeypatch)
    _patch_client(monkeypatch, lambda req: httpx.Response(500, content=b"boom internal"))
    with pytest.raises(ActorError, match="returned 500: boom internal"):
        asyncio.run(dispatch_tool("t.x", {}))


def test_dispatch_tool_non_json_response_wrapped(monkeypatch):
    """200 인데 body 가 JSON 아니면 {status, result: text} 로 감싼다."""
    _patch_actor_url(monkeypatch)
    _patch_client(
        monkeypatch,
        lambda req: httpx.Response(
            200, content=b"plain text", headers={"content-type": "text/plain"}
        ),
    )
    out = asyncio.run(dispatch_tool("t.x", {}))
    assert out == {"status": "success", "result": "plain text"}


def test_dispatch_tool_busy_retry_then_success(monkeypatch):
    """503(tool 풀 포화) → backoff sleep 후 재시도, 다음 호출에서 success."""
    _patch_actor_url(monkeypatch)
    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["calls"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"done": True})

    _patch_client(monkeypatch, handler)
    slept = _no_sleep(monkeypatch)
    out = asyncio.run(dispatch_tool("t.x", {}))
    assert out == {"done": True}
    # 첫 503 → sleep(bo * 2**0) 한 번
    assert slept == [D.settings.BUSY_BACKOFF_S]


def test_dispatch_tool_all_busy_exhausts_budget(monkeypatch):
    """계속 503 → 시간예산(budget_s) 소진 시 AllActorsBusy. 횟수 상한 폐기 (B-1)."""
    _patch_actor_url(monkeypatch)
    _patch_client(monkeypatch, lambda req: httpx.Response(503))
    slept = _fake_clock(monkeypatch)
    with pytest.raises(AllActorsBusy, match="actor busy for tool t.x"):
        # backoff 1,2,4 까지 예산 안 (누적 7) — 다음 8 이 예산 초과 → 종결
        asyncio.run(dispatch_tool("t.x", {}, backoff=1.0, budget_s=7.0))
    assert slept == [1.0, 2.0, 4.0]


def test_dispatch_tool_request_error_raises_immediately(monkeypatch):
    """연결 실패 = 즉시 ActorError — 단일 대상 (영구 에러 즉시 실패, sleep 없음)."""
    _patch_actor_url(monkeypatch, "http://dead:59300")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    _patch_client(monkeypatch, handler)
    slept = _no_sleep(monkeypatch)
    with pytest.raises(ActorError, match="request failed"):
        asyncio.run(dispatch_tool("t.x", {}))
    assert slept == []


# ── dispatch_with_retry ──────────────────────────────────────────────────────


def test_dispatch_with_retry_success_first_try(monkeypatch):
    _patch_actor_url(monkeypatch)
    _patch_client(
        monkeypatch,
        lambda req: httpx.Response(200, content=_sse(("result", '{"text":"ok"}'))),
    )
    slept = _no_sleep(monkeypatch)
    out = asyncio.run(dispatch_with_retry(2, "c", "rt", "u", "inv"))
    assert out == {"text": "ok"}
    assert slept == []  # 성공이라 재시도 없음


def test_dispatch_with_retry_busy_then_success(monkeypatch):
    """첫 attempt 전부 busy → backoff → 둘째 attempt success. backoff 인자 override."""
    _patch_actor_url(monkeypatch)
    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["calls"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, content=_sse(("result", '{"text":"late"}')))

    _patch_client(monkeypatch, handler)
    slept = _no_sleep(monkeypatch)
    out = asyncio.run(dispatch_with_retry(2, "c", "rt", "u", "inv", backoff=0.25))
    assert out == {"text": "late"}
    assert slept == [0.25]  # 첫 busy 후 backoff(0.25 * 2**0)


def test_dispatch_with_retry_exhausts_budget_and_reraises(monkeypatch):
    """계속 busy → 시간예산(budget_s) 소진 시 AllActorsBusy 재-raise. 횟수 상한 폐기 (B-1)."""
    _patch_actor_url(monkeypatch)
    _patch_client(monkeypatch, lambda req: httpx.Response(503))
    slept = _fake_clock(monkeypatch)
    with pytest.raises(AllActorsBusy):
        asyncio.run(dispatch_with_retry(2, "c", "rt", "u", "inv", backoff=1.0, budget_s=7.0))
    # backoff 1,2,4 (누적 7) 후 다음 8 이 예산 초과 → 종결
    assert slept == [1.0, 2.0, 4.0]


def test_dispatch_with_retry_backoff_capped(monkeypatch):
    """지수 backoff 는 BUSY_BACKOFF_MAX_S(30) 로 상한 — 무한 지수 폭주 방지."""
    _patch_actor_url(monkeypatch)
    _patch_client(monkeypatch, lambda req: httpx.Response(503))
    slept = _fake_clock(monkeypatch)
    with pytest.raises(AllActorsBusy):
        # delay0=min(20,30)=20 → t=20 · delay1=min(40,30)=30 → t=50 · delay2=30 이 예산(55) 초과
        asyncio.run(dispatch_with_retry(2, "c", "rt", "u", "inv", backoff=20.0, budget_s=55.0))
    assert slept == [20.0, 30.0]  # 두 번째부터 cap=30 적용 (uncapped 면 40)
