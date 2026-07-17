"""100.Nexus dro_client — Nexus→DRO control + event SSE 클라이언트 (invoke 단위).

대상: 100.Nexus/src/dro_client.py.

분기 전수:
  control_spawn  : body 구성(user_id/work_id/persona/pipeline_id/chain_id),
                   trigger 있음/없음, resp.json 의 chain_id 반환, 없으면 인자 fallback.
  _parse_sse     : event/data 쌍 flush, multi data line join, invalid JSON → {raw},
                   event 없는 data → type "message", 빈 줄에서만 flush.
  consume_events : stream() 으로 SSE 열어 aiter_lines → _parse_sse → raw dict yield,
                   data 가 dict 아니면 skip.

httpx.AsyncClient 를 가짜 컨텍스트 매니저로 monkeypatch (dro_client.httpx.AsyncClient).
async 는 asyncio.run(...) 로 (pytest-asyncio mark 없이; 기존 suite 패턴).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "100.Nexus"))

import src.dro_client as dro_client  # noqa: E402
from src.dro_client import consume_events, control_spawn  # noqa: E402


# ── fake httpx 조각 ──────────────────────────────────────────────────────────


class _FakeResponse:
    """control_spawn 용 응답 — raise_for_status + json."""

    def __init__(self, payload: Any, status_error: Exception | None = None) -> None:
        self._payload = payload
        self._status_error = status_error

    def raise_for_status(self) -> None:
        if self._status_error is not None:
            raise self._status_error

    def json(self) -> Any:
        return self._payload


class _FakePostClient:
    """async ctx-manager client — post() 만 구현. 호출 인자 기록."""

    def __init__(self, response: _FakeResponse, captured: dict[str, Any]) -> None:
        self._response = response
        self._captured = captured

    async def __aenter__(self) -> _FakePostClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def post(self, url: str, json: Any = None) -> _FakeResponse:
        self._captured["url"] = url
        self._captured["json"] = json
        return self._response


class _FakeStreamCtx:
    """client.stream(...) 가 반환하는 async ctx-manager. aiter_lines 로 SSE line 방출."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    async def __aenter__(self) -> _FakeStreamCtx:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeStreamClient:
    """async ctx-manager client — stream() 만 구현."""

    def __init__(self, lines: list[str], captured: dict[str, Any]) -> None:
        self._lines = lines
        self._captured = captured

    async def __aenter__(self) -> _FakeStreamClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    def stream(self, method: str, url: str) -> _FakeStreamCtx:
        self._captured["method"] = method
        self._captured["url"] = url
        return _FakeStreamCtx(self._lines)


def _patch_post_client(monkeypatch, response: _FakeResponse, captured: dict[str, Any]) -> None:
    def _factory(**kw: Any) -> _FakePostClient:
        return _FakePostClient(response, captured)

    monkeypatch.setattr(dro_client.httpx, "AsyncClient", _factory)


def _patch_stream_client(monkeypatch, lines: list[str], captured: dict[str, Any]) -> None:
    def _factory(**kw: Any) -> _FakeStreamClient:
        return _FakeStreamClient(lines, captured)

    monkeypatch.setattr(dro_client.httpx, "AsyncClient", _factory)


# ── control_spawn ────────────────────────────────────────────────────────────


def test_control_spawn_body_and_returns_response_chain_id(monkeypatch):
    captured: dict[str, Any] = {}
    _patch_post_client(monkeypatch, _FakeResponse({"chain_id": "c-from-dro"}), captured)

    out = asyncio.run(
        control_spawn(
            user_id="u-1",
            work_id="i-1",
            persona=2,
            pipeline_id="P02.R00.X",
            chain_id="c-passed",
            trigger={"kind": "message", "text": "hi"},
        )
    )

    assert out == "c-from-dro"
    assert captured["url"] == f"{dro_client.settings.DRO_URL}/control/spawn"
    assert captured["json"] == {
        "user_id": "u-1",
        "work_id": "i-1",
        "persona": 2,
        "pipeline_id": "P02.R00.X",
        "chain_id": "c-passed",
        "trigger": {"kind": "message", "text": "hi"},
    }


def test_control_spawn_no_trigger_omits_key(monkeypatch):
    captured: dict[str, Any] = {}
    _patch_post_client(monkeypatch, _FakeResponse({"chain_id": "c-x"}), captured)

    asyncio.run(
        control_spawn(
            user_id="u-1",
            work_id="i-1",
            persona=1,
            pipeline_id="P01.R00.X",
            chain_id="c-x",
        )
    )

    assert "trigger" not in captured["json"]
    assert captured["json"]["persona"] == 1


def test_control_spawn_falls_back_to_passed_chain_id(monkeypatch):
    # 응답 json 에 chain_id 없음 → 인자 chain_id 로 fallback.
    captured: dict[str, Any] = {}
    _patch_post_client(monkeypatch, _FakeResponse({"status": "accepted"}), captured)

    out = asyncio.run(
        control_spawn(
            user_id="u-1",
            work_id="i-1",
            persona=2,
            pipeline_id="P02.R00.X",
            chain_id="c-fallback",
        )
    )
    assert out == "c-fallback"


def test_control_spawn_empty_chain_id_in_response_falls_back(monkeypatch):
    # 응답 chain_id 가 빈 문자열(falsy) → or 분기로 인자 chain_id 사용.
    captured: dict[str, Any] = {}
    _patch_post_client(monkeypatch, _FakeResponse({"chain_id": ""}), captured)

    out = asyncio.run(control_spawn("u-1", "i-1", 3, "P03.R00.X", "c-arg"))
    assert out == "c-arg"


def test_control_spawn_raises_on_status_error(monkeypatch):
    boom = RuntimeError("502 from dro")
    captured: dict[str, Any] = {}
    _patch_post_client(monkeypatch, _FakeResponse({"chain_id": "c"}, status_error=boom), captured)

    try:
        asyncio.run(control_spawn("u-1", "i-1", 2, "P.X", "c"))
    except RuntimeError as exc:
        assert str(exc) == "502 from dro"
    else:  # pragma: no cover
        raise AssertionError("expected RuntimeError from raise_for_status")


# ── _parse_sse (직접 호출) ───────────────────────────────────────────────────


async def _collect(agen) -> list[dict[str, Any]]:
    return [evt async for evt in agen]


async def _lines_from(raw: str):
    for line in raw.splitlines():
        yield line


def test_parse_sse_event_data_pair_and_json():
    raw = 'event: started\ndata: {"rt_id":"rt_a"}\n\n'
    out = asyncio.run(_collect(dro_client._parse_sse(_lines_from(raw))))
    assert out == [{"type": "started", "data": {"rt_id": "rt_a"}}]


def test_parse_sse_multi_data_lines_joined():
    # 두 data 라인 → "\n" join 후 JSON parse.
    raw = 'event: chunk\ndata: {"a":1,\ndata: "b":2}\n\n'
    out = asyncio.run(_collect(dro_client._parse_sse(_lines_from(raw))))
    assert out == [{"type": "chunk", "data": {"a": 1, "b": 2}}]


def test_parse_sse_invalid_json_becomes_raw():
    raw = "data: not-json\n\n"
    out = asyncio.run(_collect(dro_client._parse_sse(_lines_from(raw))))
    # event 라인 없음 → type "message", invalid JSON → {"raw": payload}.
    assert out == [{"type": "message", "data": {"raw": "not-json"}}]


def test_parse_sse_event_only_yields_empty_dict():
    # data 없이 event 만 → payload "" → {} (json.loads 호출 안 함).
    raw = "event: ping\n\n"
    out = asyncio.run(_collect(dro_client._parse_sse(_lines_from(raw))))
    assert out == [{"type": "ping", "data": {}}]


def test_parse_sse_blank_with_nothing_buffered_skips():
    # 선행 빈 줄들 → event/data 둘 다 없음 → flush 안 함. 이후 정상 1건.
    raw = '\n\nevent: ok\ndata: {"v":1}\n\n'
    out = asyncio.run(_collect(dro_client._parse_sse(_lines_from(raw))))
    assert out == [{"type": "ok", "data": {"v": 1}}]


def test_parse_sse_trailing_without_blank_not_flushed():
    # 마지막 event/data 가 빈 줄로 끝나지 않으면 flush 되지 않는다.
    raw = 'event: started\ndata: {"x":1}'
    out = asyncio.run(_collect(dro_client._parse_sse(_lines_from(raw))))
    assert out == []


# ── consume_events ───────────────────────────────────────────────────────────


def test_consume_events_yields_raw_dicts(monkeypatch):
    lines = [
        "event: rt_started",
        'data: {"type":"rt_started","seq":1}',
        "",
        "event: chain_completed",
        'data: {"type":"chain_completed","seq":2}',
        "",
    ]
    captured: dict[str, Any] = {}
    _patch_stream_client(monkeypatch, lines, captured)

    out = asyncio.run(_collect(consume_events("u-1", "i-1")))
    assert out == [
        {"type": "rt_started", "seq": 1},
        {"type": "chain_completed", "seq": 2},
    ]
    assert captured["method"] == "GET"
    assert captured["url"] == (f"{dro_client.settings.DRO_URL}/events/u-1/i-1")


def test_consume_events_skips_non_dict_data(monkeypatch):
    # data 가 dict 가 아닌(list / scalar / raw 문자열) 이벤트는 skip.
    lines = [
        "data: [1, 2, 3]",  # list → skip
        "",
        "data: 42",  # int → skip
        "",
        "data: plain-text",  # invalid JSON → {"raw": ...} dict → yield
        "",
        'data: {"ok":true}',  # dict → yield
        "",
    ]
    captured: dict[str, Any] = {}
    _patch_stream_client(monkeypatch, lines, captured)

    out = asyncio.run(_collect(consume_events("u-2", "i-2")))
    assert out == [{"raw": "plain-text"}, {"ok": True}]


def test_consume_events_empty_stream(monkeypatch):
    captured: dict[str, Any] = {}
    _patch_stream_client(monkeypatch, [], captured)
    out = asyncio.run(_collect(consume_events("u-3", "i-3")))
    assert out == []


# ── control_output (C6 — docx 빌드 요청, 동기) ────────────────────────────────


class _FakeOutResponse:
    """control_output 용 응답 — status_code + raise_for_status + json."""

    def __init__(
        self, status_code: int, payload: Any, status_error: Exception | None = None
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self._status_error = status_error

    def raise_for_status(self) -> None:
        if self._status_error is not None:
            raise self._status_error

    def json(self) -> Any:
        return self._payload


def test_control_output_builds_body_and_returns_dict(monkeypatch):
    from src.dro_client import control_output

    captured: dict[str, Any] = {}
    resp = _FakeOutResponse(
        200, {"document_id": "draft", "filename": "draft.docx", "size_bytes": 4096}
    )
    _patch_post_client(monkeypatch, resp, captured)

    out = asyncio.run(control_output("u-1", "i-1", "draft"))
    assert out == {"document_id": "draft", "filename": "draft.docx", "size_bytes": 4096}
    assert captured["url"] == f"{dro_client.settings.DRO_URL}/control/output"
    assert captured["json"] == {"user_id": "u-1", "work_id": "i-1", "variant": "draft"}


def test_control_output_404_translates_to_content_not_ready(monkeypatch):
    from src.dro_client import control_output
    from src.errors import APIError
    from venezia_contracts.models.dro_api.error import ErrorCode

    captured: dict[str, Any] = {}
    _patch_post_client(monkeypatch, _FakeOutResponse(404, {"error": {}}), captured)

    try:
        asyncio.run(control_output("u-1", "i-1", "draft"))
    except APIError as exc:
        assert exc.code == ErrorCode.content_not_ready
        assert exc.status == 404
    else:  # pragma: no cover
        raise AssertionError("expected APIError content_not_ready")


def test_control_output_non_dict_json_returns_empty(monkeypatch):
    from src.dro_client import control_output

    captured: dict[str, Any] = {}
    _patch_post_client(monkeypatch, _FakeOutResponse(200, [1, 2, 3]), captured)
    out = asyncio.run(control_output("u-1", "i-1", "draft"))
    assert out == {}


def test_control_output_other_status_raises(monkeypatch):
    from src.dro_client import control_output

    boom = RuntimeError("500 from dro")
    captured: dict[str, Any] = {}
    _patch_post_client(monkeypatch, _FakeOutResponse(500, {}, status_error=boom), captured)
    try:
        asyncio.run(control_output("u-1", "i-1", "draft"))
    except RuntimeError as exc:
        assert str(exc) == "500 from dro"
    else:  # pragma: no cover
        raise AssertionError("expected RuntimeError from raise_for_status")
