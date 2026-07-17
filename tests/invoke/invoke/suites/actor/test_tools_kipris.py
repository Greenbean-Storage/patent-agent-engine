"""KIPRIS wrapper 도구 전수 (invoke 단위) — 300.Actor/src/tools/kipris/__init__.py.

대상 2 handler (register 등록):
  - kipris.search_patents   — queries(list) 병렬 / 단일 query / 둘 다 없음 분기,
    빈 query → 빈 patents, gather 의 예외 정규화(error 필드), KIPRIS_API_KEY 누락 → raise.
  - kipris.get_patent_detail — 상세 조회 + None detail 처리, 키 누락 → raise.

전략: 모듈의 `_client()` 를 monkeypatch 해 AsyncMock KiprisClient 반환 — HTTP/config 우회.
settings.KIPRIS_API_KEY 를 monkeypatch 해 키 유무 분기. search_patents / get_patent_detail
호출 인자·결과를 진짜 assert. PatentSearchResult/Detail.to_dict() 가 그대로 묶이는지 확인.

async 는 asyncio.run(...) (pytest-asyncio mark 없이; suite 패턴).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "300.Actor"))
sys.path.insert(0, str(ROOT / "shared"))

from src.config import settings  # noqa: E402
from src.tools import get as tool_get  # noqa: E402
from src.tools import kipris as kipris_mod  # noqa: E402


class _Result:
    """to_dict() 를 가진 PatentSearchResult/Detail 대역."""

    def __init__(self, d: dict) -> None:
        self._d = d

    def to_dict(self) -> dict:
        return self._d


@pytest.fixture
def with_key(monkeypatch):
    """KIPRIS_API_KEY 존재 + real 모드 강제 (호스트 profile 오염 차단)."""
    monkeypatch.setattr(settings, "KIPRIS_MODE", "real")
    monkeypatch.setattr(settings, "KIPRIS_API_KEY", "TEST-KEY")
    yield


@pytest.fixture
def fake_mode(monkeypatch):
    """KIPRIS_MODE=fake — canned fixtures 사용, 키 불요, 실 client 미접촉 증명."""
    monkeypatch.setattr(settings, "KIPRIS_MODE", "fake")
    monkeypatch.setattr(settings, "KIPRIS_API_KEY", "")  # fake = 키 불요가 목적
    monkeypatch.setattr(
        settings, "KIPRIS_FIXTURE_DIR", str(ROOT / "tests" / "data" / "kipris-fixtures")
    )
    monkeypatch.setattr(
        kipris_mod, "_client", lambda: pytest.fail("fake 모드에서 _client() 호출 금지")
    )
    yield


@pytest.fixture
def mock_client(monkeypatch):
    """`_client()` 가 AsyncMock KiprisClient 를 반환하도록 교체."""
    fake = AsyncMock()
    monkeypatch.setattr(kipris_mod, "_client", lambda: fake)
    return fake


# ── registry ──────────────────────────────────────────────────────────────────


def test_handlers_registered():
    assert tool_get("kipris.search_patents") is kipris_mod.search_patents
    assert tool_get("kipris.get_patent_detail") is kipris_mod.get_patent_detail


# ── search_patents: queries(list) ────────────────────────────────────────────────


def test_search_patents_queries_list_parallel(with_key, mock_client):
    """queries list → 각 query 검색 후 results 로 묶음. patents 는 to_dict() 직렬화."""
    mock_client.search_patents.return_value = [_Result({"application_number": "10-1"})]
    out = asyncio.run(
        kipris_mod.search_patents(
            queries=[{"query": "로봇"}, {"query": "센서"}],
            max_results_per_query=7,
        )
    )
    assert out == {
        "results": [
            {"query": "로봇", "patents": [{"application_number": "10-1"}]},
            {"query": "센서", "patents": [{"application_number": "10-1"}]},
        ]
    }
    # 각 query 마다 max_results_per_query 로 호출
    assert mock_client.search_patents.await_count == 2
    mock_client.search_patents.assert_any_await("로봇", max_results=7)
    mock_client.search_patents.assert_any_await("센서", max_results=7)


def test_search_patents_queries_non_dict_item_coerced_to_str(with_key, mock_client):
    """q_item 이 dict 아님 → str(q_item) 로 fallback."""
    mock_client.search_patents.return_value = []
    out = asyncio.run(kipris_mod.search_patents(queries=["plainstring"]))
    assert out == {"results": [{"query": "plainstring", "patents": []}]}
    mock_client.search_patents.assert_awaited_once_with("plainstring", max_results=10)


def test_search_patents_queries_empty_query_short_circuits(with_key, mock_client):
    """query 텍스트 빈 → KIPRIS 호출 없이 빈 patents (_one 의 not q_text 분기)."""
    out = asyncio.run(kipris_mod.search_patents(queries=[{"query": ""}, {"foo": "bar"}]))
    assert out == {
        "results": [
            {"query": "", "patents": []},
            {"query": "", "patents": []},
        ]
    }
    mock_client.search_patents.assert_not_awaited()


def test_search_patents_queries_exception_normalized(with_key, mock_client):
    """gather(return_exceptions=True) — 한 query 가 raise 하면 error 필드로 정규화."""

    async def _side(q_text, max_results):
        if q_text == "bad":
            raise RuntimeError("kipris down")
        return [_Result({"application_number": "ok"})]

    mock_client.search_patents.side_effect = _side
    out = asyncio.run(kipris_mod.search_patents(queries=[{"query": "good"}, {"query": "bad"}]))
    assert out["results"][0] == {
        "query": "good",
        "patents": [{"application_number": "ok"}],
    }
    assert out["results"][1] == {"query": "", "patents": [], "error": "kipris down"}


# ── search_patents: 단일 query / none ────────────────────────────────────────────


def test_search_patents_single_query(with_key, mock_client):
    mock_client.search_patents.return_value = [_Result({"application_number": "10-5"})]
    out = asyncio.run(kipris_mod.search_patents(query="단일", max_results=20))
    assert out == {"query": "단일", "patents": [{"application_number": "10-5"}]}
    mock_client.search_patents.assert_awaited_once_with("단일", max_results=20)


def test_search_patents_no_queries_no_query_returns_empty(with_key, mock_client):
    """queries 도 query 도 없음 → {'results': []} (KIPRIS 미호출)."""
    out = asyncio.run(kipris_mod.search_patents())
    assert out == {"results": []}
    mock_client.search_patents.assert_not_awaited()


def test_search_patents_empty_queries_list_falls_through_to_query(with_key, mock_client):
    """queries=[] (falsy) → queries 분기 skip, query 도 없음 → results []."""
    out = asyncio.run(kipris_mod.search_patents(queries=[]))
    assert out == {"results": []}
    mock_client.search_patents.assert_not_awaited()


# ── search_patents: 키 누락 ──────────────────────────────────────────────────────


def test_search_patents_missing_key_raises(monkeypatch, mock_client):
    monkeypatch.setattr(settings, "KIPRIS_MODE", "real")
    monkeypatch.setattr(settings, "KIPRIS_API_KEY", "")
    with pytest.raises(RuntimeError, match="KIPRIS_API_KEY not set"):
        asyncio.run(kipris_mod.search_patents(query="x"))
    mock_client.search_patents.assert_not_awaited()


# ── get_patent_detail ────────────────────────────────────────────────────────────


def test_get_patent_detail_returns_detail(with_key, mock_client):
    mock_client.get_patent_detail.return_value = _Result(
        {"application_number": "10-9", "title": "T"}
    )
    out = asyncio.run(kipris_mod.get_patent_detail("10-9"))
    assert out == {
        "application_number": "10-9",
        "detail": {"application_number": "10-9", "title": "T"},
    }
    mock_client.get_patent_detail.assert_awaited_once_with("10-9")


def test_get_patent_detail_none_detail(with_key, mock_client):
    """client 가 None 반환 → detail None 분기."""
    mock_client.get_patent_detail.return_value = None
    out = asyncio.run(kipris_mod.get_patent_detail("missing"))
    assert out == {"application_number": "missing", "detail": None}


def test_get_patent_detail_missing_key_raises(monkeypatch, mock_client):
    monkeypatch.setattr(settings, "KIPRIS_MODE", "real")
    monkeypatch.setattr(settings, "KIPRIS_API_KEY", "")
    with pytest.raises(RuntimeError, match="KIPRIS_API_KEY not set"):
        asyncio.run(kipris_mod.get_patent_detail("x"))
    mock_client.get_patent_detail.assert_not_awaited()


# ── KIPRIS_MODE=fake (3k — canned, tests/data/kipris-fixtures 단일 소스) ──────────


def _pool() -> list[dict]:
    import json

    return json.loads(
        (ROOT / "tests" / "data" / "kipris-fixtures" / "search_pool.json").read_text(
            encoding="utf-8"
        )
    )


def _details() -> dict:
    import json

    return json.loads(
        (ROOT / "tests" / "data" / "kipris-fixtures" / "details.json").read_text(encoding="utf-8")
    )


def test_fake_search_queries_list(fake_mode):
    """fake: 모든 query 가 pool[:max_results_per_query] — canned 의미론 (mock canned 동형)."""
    pool = _pool()
    out = asyncio.run(
        kipris_mod.search_patents(
            queries=[{"query": "로봇"}, {"query": "센서"}], max_results_per_query=3
        )
    )
    assert out == {
        "results": [
            {"query": "로봇", "patents": pool[:3]},
            {"query": "센서", "patents": pool[:3]},
        ]
    }


def test_fake_search_queries_non_dict_item(fake_mode):
    """fake: q_item 비 dict → str coerce. 빈 query 텍스트도 pool 반환 (canned 미러)."""
    pool = _pool()
    out = asyncio.run(kipris_mod.search_patents(queries=["plain", {"foo": "bar"}]))
    assert out["results"][0] == {"query": "plain", "patents": pool[:10]}
    assert out["results"][1] == {"query": "", "patents": pool[:10]}


def test_fake_search_single_query(fake_mode):
    pool = _pool()
    out = asyncio.run(kipris_mod.search_patents(query="단일", max_results=5))
    assert out == {"query": "단일", "patents": pool[:5]}


def test_fake_search_no_args_empty(fake_mode):
    assert asyncio.run(kipris_mod.search_patents()) == {"results": []}


def test_fake_detail_found(fake_mode):
    details = _details()
    app_no = next(iter(details))
    out = asyncio.run(kipris_mod.get_patent_detail(app_no))
    assert out == {"application_number": app_no, "detail": details[app_no]}


def test_fake_detail_missing_none(fake_mode):
    out = asyncio.run(kipris_mod.get_patent_detail("0000000000000"))
    assert out == {"application_number": "0000000000000", "detail": None}


def test_unknown_kipris_mode_raises(monkeypatch, mock_client):
    """KIPRIS_MODE 가 real|fake 외 → fail-loud (두 handler 공통)."""
    monkeypatch.setattr(settings, "KIPRIS_MODE", "bogus")
    with pytest.raises(RuntimeError, match="unknown KIPRIS_MODE"):
        asyncio.run(kipris_mod.search_patents(query="x"))
    with pytest.raises(RuntimeError, match="unknown KIPRIS_MODE"):
        asyncio.run(kipris_mod.get_patent_detail("x"))
    mock_client.search_patents.assert_not_awaited()
    mock_client.get_patent_detail.assert_not_awaited()


# ── _client() (lazy import) ──────────────────────────────────────────────────────


def test_client_returns_singleton(monkeypatch):
    """_client() 가 get_kipris_client() 를 lazy import 해 반환 — 마지막 미커버 라인."""
    import src.tools.kipris.client as real_client_mod

    sentinel = object()
    monkeypatch.setattr(real_client_mod, "get_kipris_client", lambda: sentinel)
    assert kipris_mod._client() is sentinel
