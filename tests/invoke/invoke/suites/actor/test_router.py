"""300.Actor router — POST /dispatch (SSE) + POST /tool/{name} 전수 (invoke 단위).

대상: 300.Actor/src/router.py
  - POST /dispatch:
      * 필수 키 누락 (chain_id/rt_id/user_id/work_id) → 400.
      * persona 슬롯 포화 (try_acquire_persona→False) → 503 "busy" + Retry-After.
      * engine.config 미등재 persona (RuntimeError) → 슬롯 없이 진행 (handle 이 SSE error).
      * 정상 → 200 text/event-stream, dispatcher.handle 스트림 그대로 전달,
        finally release_persona(pid).
  - POST /tool/{name} (성공 외 = ErrorEnvelope {"error":{"code","message"}}):
      * 미등록 tool → 404 code=not_found.
      * tool 풀 포화 → 503 code=rate_limited + Retry-After (dispatch 와 별도 풀).
      * params 가 dict 아님 → 400 code=validation_failed.
      * handler TypeError (잘못된 인자) → 400 code=validation_failed.
      * handler 예외 → 500 code=internal (메시지 500자 절단).
      * 정상 → 200 {"status":"success","result":...}, params 전달, finally release_tool().
      * tool_name path converter (`:path`) → 슬래시 포함 이름.

전략: router 를 fresh FastAPI app 에 mount (src.main 의 secrets/AWS import 회피).
slots.try_acquire_persona/release_persona/try_acquire_tool/release_tool +
dispatcher.handle + tools.get 를 monkeypatch — 벤더 SDK·CM 무관.
httpx ASGITransport 로 호출. 진짜 assert (status·body·헤더·release 호출 여부).

async 는 asyncio.run(...) (pytest-asyncio mark 없이; 기존 suite 패턴).
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "300.Actor"))

from src import dispatcher, slots, tools  # noqa: E402
from src.router import router  # noqa: E402

_BODY = {"chain_id": "ch1", "rt_id": "rt1", "user_id": "u1", "work_id": "inv1", "persona": 1}


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


class _Release:
    """release 호출 여부(+인자)를 기록하는 콜러블."""

    def __init__(self) -> None:
        self.called = 0
        self.args: list[tuple] = []

    def __call__(self, *a) -> None:
        self.called += 1
        self.args.append(a)


def _patch_persona_acquire(monkeypatch, ok: bool) -> None:
    async def _acq(pid: int) -> bool:
        return ok

    monkeypatch.setattr(slots, "try_acquire_persona", _acq)


def _patch_tool_acquire(monkeypatch, ok: bool) -> None:
    async def _acq() -> bool:
        return ok

    monkeypatch.setattr(slots, "try_acquire_tool", _acq)


# ── POST /dispatch ──────────────────────────────────────────────────────────────


def test_dispatch_missing_keys_returns_400(monkeypatch):
    # 슬롯 acquire 가 불려선 안 됨 — 호출되면 실패하도록.
    async def _boom(pid: int) -> bool:  # pragma: no cover - 호출되면 테스트 실패
        raise AssertionError("try_acquire_persona must not be called on 400")

    monkeypatch.setattr(slots, "try_acquire_persona", _boom)
    app = _app()

    async def _run():
        async with _client(app) as c:
            r = await c.post("/dispatch", json={"chain_id": "ch1"})  # rt_id 등 누락
            assert r.status_code == 400
            assert "required" in r.text

    asyncio.run(_run())


def test_dispatch_busy_returns_503_with_retry_after(monkeypatch):
    _patch_persona_acquire(monkeypatch, ok=False)
    rel = _Release()
    monkeypatch.setattr(slots, "release_persona", rel)
    app = _app()

    async def _run():
        async with _client(app) as c:
            r = await c.post("/dispatch", json=_BODY)
            assert r.status_code == 503
            assert r.json()["error"]["code"] == "rate_limited"
            # 포화 ≠ 실패 — DRO 의 시간예산 재시도 힌트 (B-1)
            assert r.headers["retry-after"] == "1"

    asyncio.run(_run())
    # busy 분기는 release 를 호출하지 않는다 (acquire 실패 시 stream 미생성).
    assert rel.called == 0


def test_dispatch_unknown_persona_proceeds_without_slot(monkeypatch):
    """engine.config 미등재 persona — 슬롯 없이 진행, handle 이 SSE error 로 거절 (계약 보존)."""

    async def _acq(pid: int) -> bool:
        raise RuntimeError("persona 99 가 engine config 에 없음")

    monkeypatch.setattr(slots, "try_acquire_persona", _acq)
    rel = _Release()
    monkeypatch.setattr(slots, "release_persona", rel)

    async def _handle(user_id, work_id, chain_id, rt_id, persona) -> AsyncIterator[str]:
        yield "event: started\ndata: {}\n\n"
        yield 'event: error\ndata: {"message": "persona 99 not handled"}\n\n'

    monkeypatch.setattr(dispatcher, "handle", _handle)
    app = _app()

    async def _run():
        async with _client(app) as c:
            r = await c.post("/dispatch", json={**_BODY, "persona": 99})
            assert r.status_code == 200
            assert "event: error" in r.text

    asyncio.run(_run())
    # 슬롯을 잡지 않았으므로 release 도 없다.
    assert rel.called == 0


def test_dispatch_success_streams_and_releases(monkeypatch):
    _patch_persona_acquire(monkeypatch, ok=True)
    rel = _Release()
    monkeypatch.setattr(slots, "release_persona", rel)

    seen: dict[str, Any] = {}

    async def _handle(user_id, work_id, chain_id, rt_id, persona) -> AsyncIterator[str]:
        seen.update(
            user_id=user_id, work_id=work_id, chain_id=chain_id, rt_id=rt_id, persona=persona
        )
        yield "event: started\ndata: {}\n\n"
        yield 'event: result\ndata: {"ok": true}\n\n'

    monkeypatch.setattr(dispatcher, "handle", _handle)
    app = _app()

    async def _run():
        async with _client(app) as c:
            r = await c.post("/dispatch", json=_BODY)
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            assert "event: started" in r.text
            assert "event: result" in r.text

    asyncio.run(_run())
    # handle 이 body 인자를 그대로 받았는지.
    assert seen == {
        "user_id": "u1",
        "work_id": "inv1",
        "chain_id": "ch1",
        "rt_id": "rt1",
        "persona": 1,
    }
    # stream finally → release_persona(pid) 정확히 1회.
    assert rel.called == 1
    assert rel.args == [(1,)]


# ── POST /tool/{name} ─────────────────────────────────────────────────────────


def test_tool_not_registered_returns_404(monkeypatch):
    monkeypatch.setattr(tools, "get", lambda name: None)
    app = _app()

    async def _run():
        async with _client(app) as c:
            r = await c.post("/tool/kipris.nope", json={"params": {}})
            assert r.status_code == 404
            body = r.json()
            assert body["error"]["code"] == "not_found"
            assert "kipris.nope" in body["error"]["message"]

    asyncio.run(_run())


def test_tool_busy_returns_503_with_retry_after(monkeypatch):
    async def _handler(**kw):  # pragma: no cover - busy 면 호출 안 됨
        return {"ok": True}

    monkeypatch.setattr(tools, "get", lambda name: _handler)
    _patch_tool_acquire(monkeypatch, ok=False)
    rel = _Release()
    monkeypatch.setattr(slots, "release_tool", rel)
    app = _app()

    async def _run():
        async with _client(app) as c:
            r = await c.post("/tool/some.tool", json={"params": {}})
            assert r.status_code == 503
            assert r.json()["error"]["code"] == "rate_limited"
            assert r.headers["retry-after"] == "1"

    asyncio.run(_run())
    assert rel.called == 0


def test_tool_params_not_dict_returns_400(monkeypatch):
    async def _handler(**kw):  # pragma: no cover - bad_params 면 호출 안 됨
        return {"ok": True}

    monkeypatch.setattr(tools, "get", lambda name: _handler)
    _patch_tool_acquire(monkeypatch, ok=True)
    rel = _Release()
    monkeypatch.setattr(slots, "release_tool", rel)
    app = _app()

    async def _run():
        async with _client(app) as c:
            r = await c.post("/tool/some.tool", json={"params": [1, 2, 3]})
            assert r.status_code == 400
            body = r.json()
            assert body["error"]["code"] == "validation_failed"
            assert "dict" in body["error"]["message"]

    asyncio.run(_run())
    # bad_params 도 finally 의 release 를 탄다 (acquire 성공 후).
    assert rel.called == 1


def test_tool_type_error_returns_400(monkeypatch):
    async def _handler(*, required_arg):
        return {"got": required_arg}

    monkeypatch.setattr(tools, "get", lambda name: _handler)
    _patch_tool_acquire(monkeypatch, ok=True)
    rel = _Release()
    monkeypatch.setattr(slots, "release_tool", rel)
    app = _app()

    async def _run():
        async with _client(app) as c:
            # params 없는 인자 → handler(**{}) → TypeError(required_arg 누락).
            r = await c.post("/tool/some.tool", json={"params": {"wrong": 1}})
            assert r.status_code == 400
            assert r.json()["error"]["code"] == "validation_failed"

    asyncio.run(_run())
    assert rel.called == 1


def test_tool_handler_exception_returns_500_truncated(monkeypatch):
    long_msg = "x" * 1000

    async def _handler(**kw):
        raise RuntimeError(long_msg)

    monkeypatch.setattr(tools, "get", lambda name: _handler)
    _patch_tool_acquire(monkeypatch, ok=True)
    rel = _Release()
    monkeypatch.setattr(slots, "release_tool", rel)
    app = _app()

    async def _run():
        async with _client(app) as c:
            r = await c.post("/tool/some.tool", json={"params": {}})
            assert r.status_code == 500
            body = r.json()
            assert body["error"]["code"] == "internal"
            # str(e)[:500] 절단 — 1000자가 500자로.
            assert len(body["error"]["message"]) == 500

    asyncio.run(_run())
    assert rel.called == 1


def test_tool_success_passes_params_and_releases(monkeypatch):
    captured: dict[str, Any] = {}

    async def _handler(**kw):
        captured.update(kw)
        return {"echo": kw}

    monkeypatch.setattr(tools, "get", lambda name: _handler)
    _patch_tool_acquire(monkeypatch, ok=True)
    rel = _Release()
    monkeypatch.setattr(slots, "release_tool", rel)
    app = _app()

    async def _run():
        async with _client(app) as c:
            r = await c.post("/tool/kipris.search_patents", json={"params": {"queries": ["a"]}})
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == "success"
            assert body["result"] == {"echo": {"queries": ["a"]}}

    asyncio.run(_run())
    assert captured == {"queries": ["a"]}
    assert rel.called == 1


def test_tool_records_rt_when_identifiers_present(monkeypatch):
    """tool=RT 통일(N-7) — rt 식별자가 오면 tool 출력을 그 RT 레코드에 patch_rt (LLM 대칭)."""
    recorded: dict[str, Any] = {}

    async def _handler(**kw):
        return {"score": 0.5}

    class _CM:
        async def patch_rt(self, user_id, work_id, persona, chain_id, rt_id, fields):
            recorded.update(
                user_id=user_id,
                work_id=work_id,
                persona=persona,
                chain_id=chain_id,
                rt_id=rt_id,
                fields=fields,
            )
            return {"ok": True}

    monkeypatch.setattr(tools, "get", lambda name: _handler)
    _patch_tool_acquire(monkeypatch, ok=True)
    monkeypatch.setattr(slots, "release_tool", lambda: None)
    monkeypatch.setattr("src.router.get_cm_client", lambda: _CM())
    app = _app()

    async def _run():
        async with _client(app) as c:
            r = await c.post(
                "/tool/maturity.compute",
                json={
                    "params": {"x": 1},
                    "user_id": "u",
                    "work_id": "inv",
                    "persona": 2,
                    "chain_id": "c1",
                    "rt_id": "rt9",
                },
            )
            assert r.status_code == 200
            assert r.json()["result"] == {"score": 0.5}

    asyncio.run(_run())
    assert recorded["rt_id"] == "rt9"
    assert recorded["persona"] == 2
    assert recorded["fields"] == {"output": {"score": 0.5}, "state": "done"}


def test_tool_record_rt_non_dict_result_wrapped(monkeypatch):
    """tool 결과가 dict 아니면 {"result": ...} 로 wrap 후 기록 (RT output contract = object)."""
    recorded: dict[str, Any] = {}

    async def _handler(**kw):
        return [1, 2, 3]

    class _CM:
        async def patch_rt(self, user_id, work_id, persona, chain_id, rt_id, fields):
            recorded.update(fields=fields)
            return {"ok": True}

    monkeypatch.setattr(tools, "get", lambda name: _handler)
    _patch_tool_acquire(monkeypatch, ok=True)
    monkeypatch.setattr(slots, "release_tool", lambda: None)
    monkeypatch.setattr("src.router.get_cm_client", lambda: _CM())
    app = _app()

    async def _run():
        async with _client(app) as c:
            r = await c.post(
                "/tool/some.tool",
                json={
                    "params": {},
                    "user_id": "u",
                    "work_id": "inv",
                    "persona": 1,
                    "chain_id": "c1",
                    "rt_id": "rtZ",
                },
            )
            assert r.status_code == 200

    asyncio.run(_run())
    assert recorded["fields"] == {"output": {"result": [1, 2, 3]}, "state": "done"}


def test_tool_record_rt_cm_failure_swallowed(monkeypatch):
    """RT 기록 중 CM 실패는 best-effort swallow — tool 응답은 200 (DRO 가 이어서 finalize)."""

    async def _handler(**kw):
        return {"ok": True}

    class _CM:
        async def patch_rt(self, *a, **k):
            raise RuntimeError("cm down")

    monkeypatch.setattr(tools, "get", lambda name: _handler)
    _patch_tool_acquire(monkeypatch, ok=True)
    monkeypatch.setattr(slots, "release_tool", lambda: None)
    monkeypatch.setattr("src.router.get_cm_client", lambda: _CM())
    app = _app()

    async def _run():
        async with _client(app) as c:
            r = await c.post(
                "/tool/some.tool",
                json={
                    "params": {},
                    "user_id": "u",
                    "work_id": "inv",
                    "persona": 1,
                    "chain_id": "c1",
                    "rt_id": "rtE",
                },
            )
            assert r.status_code == 200
            assert r.json()["status"] == "success"

    asyncio.run(_run())


def test_tool_default_body_empty_params(monkeypatch):
    """body 미지정 (default {}) → params {} → handler() 무인자 호출."""
    called: dict[str, Any] = {}

    async def _handler(**kw):
        called["kw"] = kw
        return {"ok": True}

    monkeypatch.setattr(tools, "get", lambda name: _handler)
    _patch_tool_acquire(monkeypatch, ok=True)
    monkeypatch.setattr(slots, "release_tool", lambda: None)
    app = _app()

    async def _run():
        async with _client(app) as c:
            r = await c.post("/tool/some.tool")
            assert r.status_code == 200
            assert r.json()["result"] == {"ok": True}

    asyncio.run(_run())
    assert called["kw"] == {}


def test_tool_name_with_slash_path_converter(monkeypatch):
    """`{tool_name:path}` 컨버터 — 슬래시 포함 이름도 get() 에 전달."""
    seen_names: list[str] = []

    def _get(name: str):
        seen_names.append(name)
        return None  # not registered → 404

    monkeypatch.setattr(tools, "get", _get)
    app = _app()

    async def _run():
        async with _client(app) as c:
            r = await c.post("/tool/a/b/c", json={"params": {}})
            assert r.status_code == 404

    asyncio.run(_run())
    assert seen_names == ["a/b/c"]
