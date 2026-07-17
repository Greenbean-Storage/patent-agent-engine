"""KIPRIS Plus API 클라이언트 전수 (invoke 단위) — 300.Actor/src/tools/kipris/client.py.

대상: KiprisClient (search_patents / get_patent_detail / _parse_xml_response / close) +
PatentSearchResult / PatentDetail dataclass + get_kipris_client 싱글톤.

전략: httpx.MockTransport(handler) 를 KiprisClient._client 에 주입 — handler 가 url path +
params 로 canned XML 응답을 돌려준다. 캐시는 격리된 ContextCache 를 직접 주입(전역 오염 방지).
검증 포인트(진짜 assert):
  - search: 올바른 endpoint + params(word/year/numOfRows/ServiceKey 등) 호출, XML 파싱
    (applicationNumber/inventionTitle/applicantName/applicationDate[:10]/astrtCont/ipcNumber),
    max_results 슬라이싱, astrtCont 빈값 → "내용 없음", ipcNumber 빈값 → [] 분기.
  - cache: results 있으면 set, 두번째 호출 hit (HTTP 미발생). use_cache=False 면 매번 HTTP.
    캐시 hit 시 PatentSearchResult(**r) 재구성.
  - search HTTPError → raise (raise_for_status 4xx/5xx).
  - get_patent_detail: 올바른 endpoint, 첫 item 파싱(openDate/registerDate → [:10] or None,
    inventorName default "정보 없음", claims=[]), items 없으면 None, HTTPError → None (삼킴).
  - _parse_xml_response: 정상 다중 item, child.text None → "", ParseError → [] (defusedxml).
  - close() 가 underlying client aclose.
  - get_kipris_client 싱글톤.

async 는 asyncio.run(...) (pytest-asyncio mark 없이; suite 패턴).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "300.Actor"))
sys.path.insert(0, str(ROOT / "shared"))

from src.tools.kipris import client as client_mod  # noqa: E402
from src.tools.kipris.cache import ContextCache  # noqa: E402
from src.tools.kipris.client import (  # noqa: E402
    KiprisClient,
    PatentDetail,
    PatentSearchResult,
    get_kipris_client,
)

# base_url(settings.KIPRIS_BASE_URL) 의 path prefix 까지 포함한 전체 path.
_SEARCH_PATH = "/kipo-api/kipi/patUtiModInfoSearchSevice/getWordSearch"
_DETAIL_PATH = "/kipo-api/kipi/patUtiModInfoSearchSevice/getAdvancedSearch"


class _Capture:
    def __init__(self) -> None:
        self.method: str | None = None
        self.path: str | None = None
        self.params: dict[str, str] = {}


def _search_xml(*items: dict[str, str]) -> str:
    """KIPRIS getWordSearch 스타일 XML — .//item 아래 child 태그."""
    body = []
    for it in items:
        children = "".join(f"<{k}>{v}</{k}>" for k, v in it.items())
        body.append(f"<item>{children}</item>")
    return f"<response><body><items>{''.join(body)}</items></body></response>"


def _make_client(handler, capture: _Capture | None = None) -> KiprisClient:
    """MockTransport 주입 + 격리 캐시. handler(request)->Response."""
    cap = capture or _Capture()

    def _wrapped(request: httpx.Request) -> httpx.Response:
        cap.method = request.method
        cap.path = request.url.path
        cap.params = dict(request.url.params)
        return handler(request)

    c = KiprisClient()
    c._client = httpx.AsyncClient(transport=httpx.MockTransport(_wrapped))
    c._cache = ContextCache(max_size=64, ttl=1000)  # 전역 캐시 오염 방지
    c.api_key = "TEST-KEY"
    return c


def _xml_ok(text: str) -> httpx.Response:
    return httpx.Response(200, text=text, headers={"content-type": "application/xml"})


# ── dataclass to_dict ────────────────────────────────────────────────────────────


def test_search_result_to_dict_roundtrip():
    r = PatentSearchResult(
        application_number="10-1",
        title="T",
        applicant="A",
        application_date="2020-01-01",
        abstract="abs",
        ipc_codes=["G06F"],
    )
    d = r.to_dict()
    assert d == {
        "application_number": "10-1",
        "title": "T",
        "applicant": "A",
        "application_date": "2020-01-01",
        "abstract": "abs",
        "ipc_codes": ["G06F"],
    }
    # to_dict → PatentSearchResult(**d) 재구성 (캐시 hit 경로가 의존)
    assert PatentSearchResult(**d) == r


def test_detail_to_dict():
    d = PatentDetail(
        application_number="10-2",
        title="T2",
        applicant="A2",
        inventor="I2",
        application_date="2021-02-02",
        publication_date="2021-03-03",
        registration_date=None,
        abstract="abs2",
        claims=[],
        ipc_codes=["H04L"],
    ).to_dict()
    assert d["application_number"] == "10-2"
    assert d["inventor"] == "I2"
    assert d["publication_date"] == "2021-03-03"
    assert d["registration_date"] is None
    assert d["claims"] == []
    assert d["ipc_codes"] == ["H04L"]


# ── _parse_xml_response ──────────────────────────────────────────────────────────


def test_parse_xml_multiple_items():
    c = _make_client(lambda r: _xml_ok(""))
    xml = _search_xml(
        {"applicationNumber": "10-1", "inventionTitle": "A"},
        {"applicationNumber": "10-2", "inventionTitle": "B"},
    )
    out = c._parse_xml_response(xml)
    assert out == [
        {"applicationNumber": "10-1", "inventionTitle": "A"},
        {"applicationNumber": "10-2", "inventionTitle": "B"},
    ]


def test_parse_xml_empty_child_text_becomes_empty_string():
    """child.text 가 None (빈 태그) → '' 로 채움."""
    c = _make_client(lambda r: _xml_ok(""))
    out = c._parse_xml_response("<r><item><applicationNumber/></item></r>")
    assert out == [{"applicationNumber": ""}]


def test_parse_xml_parse_error_returns_empty():
    """깨진 XML → ParseError 삼킴 → []."""
    c = _make_client(lambda r: _xml_ok(""))
    out = c._parse_xml_response("<not-closed>")
    assert out == []


# ── search_patents ───────────────────────────────────────────────────────────────


def test_search_patents_parses_and_sends_params():
    cap = _Capture()
    xml = _search_xml(
        {
            "applicationNumber": "10-2020-0001",
            "inventionTitle": "로봇 팔",
            "applicantName": "회사A",
            "applicationDate": "20200115",  # [:10] 슬라이스 대상
            "astrtCont": "요약 내용",
            "ipcNumber": "G06F",
        }
    )
    c = _make_client(lambda r: _xml_ok(xml), cap)
    out = asyncio.run(c.search_patents("로봇", max_results=30, year_range=5))
    assert len(out) == 1
    r = out[0]
    assert isinstance(r, PatentSearchResult)
    assert r.application_number == "10-2020-0001"
    assert r.title == "로봇 팔"
    assert r.applicant == "회사A"
    assert r.application_date == "20200115"  # 8 chars < 10 → 그대로
    assert r.abstract == "요약 내용"
    assert r.ipc_codes == ["G06F"]
    # endpoint + params
    assert cap.method == "GET"
    assert cap.path == _SEARCH_PATH
    assert cap.params["word"] == "로봇"
    assert cap.params["year"] == "5"
    assert cap.params["patent"] == "true"
    assert cap.params["utility"] == "true"
    assert cap.params["numOfRows"] == "30"
    assert cap.params["pageNo"] == "1"
    assert cap.params["ServiceKey"] == "TEST-KEY"


def test_search_patents_truncates_long_date_and_defaults():
    """applicationDate 10자 초과 → [:10] 슬라이스. astrtCont 빈값 → '내용 없음'. ipc 없음 → []."""
    xml = _search_xml(
        {
            "applicationNumber": "10-3",
            "inventionTitle": "T",
            "applicantName": "A",
            "applicationDate": "2019-12-31T00:00:00",
            "astrtCont": "",  # 빈 문자열 → "내용 없음"
            # ipcNumber 누락 → ipc_codes []
        }
    )
    c = _make_client(lambda r: _xml_ok(xml))
    out = asyncio.run(c.search_patents("q", use_cache=False))
    assert out[0].application_date == "2019-12-31"
    assert out[0].abstract == "내용 없음"
    assert out[0].ipc_codes == []


def test_search_patents_respects_max_results_slice():
    """items 가 max_results 보다 많아도 [:max_results] 만 반환."""
    items = [{"applicationNumber": f"10-{i}", "inventionTitle": f"T{i}"} for i in range(5)]
    xml = _search_xml(*items)
    c = _make_client(lambda r: _xml_ok(xml))
    out = asyncio.run(c.search_patents("q", max_results=2, use_cache=False))
    assert len(out) == 2
    assert [r.application_number for r in out] == ["10-0", "10-1"]


def test_search_patents_caches_second_call(monkeypatch):
    """첫 호출 HTTP + set, 두번째 호출 cache hit → HTTP 미발생, PatentSearchResult 재구성."""
    calls = {"n": 0}
    xml = _search_xml({"applicationNumber": "10-9", "inventionTitle": "C", "ipcNumber": "H04L"})

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _xml_ok(xml)

    c = _make_client(handler)
    first = asyncio.run(c.search_patents("cached-q", max_results=10, year_range=5))
    second = asyncio.run(c.search_patents("cached-q", max_results=10, year_range=5))
    assert calls["n"] == 1  # 두번째는 캐시 hit → HTTP 한번뿐
    assert [r.to_dict() for r in first] == [r.to_dict() for r in second]
    assert all(isinstance(r, PatentSearchResult) for r in second)
    assert c._cache.stats["hits"] == 1


def test_search_patents_use_cache_false_always_http():
    calls = {"n": 0}
    xml = _search_xml({"applicationNumber": "10-1", "inventionTitle": "C"})

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _xml_ok(xml)

    c = _make_client(handler)
    asyncio.run(c.search_patents("q", use_cache=False))
    asyncio.run(c.search_patents("q", use_cache=False))
    assert calls["n"] == 2  # 매번 HTTP


def test_search_patents_empty_results_not_cached():
    """items 0개 → results 비어있음 → cache set 안함(set 조건 `results` truthy)."""
    c = _make_client(lambda r: _xml_ok(_search_xml()))
    out = asyncio.run(c.search_patents("empty", max_results=10, year_range=5))
    assert out == []
    assert c._cache.stats["search_cache_size"] == 0


def test_search_patents_http_error_raises():
    c = _make_client(lambda r: httpx.Response(500, text="boom"))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(c.search_patents("q", use_cache=False))


# ── get_patent_detail ────────────────────────────────────────────────────────────


def test_get_patent_detail_parses_full_item():
    cap = _Capture()
    xml = _search_xml(
        {
            "applicationNumber": "10-2020-0009",
            "inventionTitle": "상세 발명",
            "applicantName": "출원인B",
            "inventorName": "발명자C",
            "applicationDate": "2020-06-01T12:00:00",
            "openDate": "2021-01-01T00:00:00",
            "registerDate": "2022-02-02T00:00:00",
            "astrtCont": "상세 요약",
            "ipcNumber": "G06N",
        }
    )
    c = _make_client(lambda r: _xml_ok(xml), cap)
    detail = asyncio.run(c.get_patent_detail("10-2020-0009"))
    assert detail is not None
    assert detail.application_number == "10-2020-0009"
    assert detail.title == "상세 발명"
    assert detail.applicant == "출원인B"
    assert detail.inventor == "발명자C"
    assert detail.application_date == "2020-06-01"
    assert detail.publication_date == "2021-01-01"
    assert detail.registration_date == "2022-02-02"
    assert detail.abstract == "상세 요약"
    assert detail.claims == []  # getAdvancedSearch 는 청구항 미반환
    assert detail.ipc_codes == ["G06N"]
    assert cap.method == "GET"
    assert cap.path == _DETAIL_PATH
    assert cap.params["applicationNumber"] == "10-2020-0009"
    assert cap.params["numOfRows"] == "1"
    assert cap.params["ServiceKey"] == "TEST-KEY"


def test_get_patent_detail_defaults_and_none_dates():
    """openDate/registerDate 없음 → None, inventorName 없음 → '정보 없음', astrtCont 빈 → '내용 없음',
    applicationNumber 없음 → 인자 fallback, ipcNumber 없음 → []."""
    xml = _search_xml(
        {
            "inventionTitle": "T",
            # applicationNumber 누락 → 인자값 fallback
            # inventorName 누락 → "정보 없음"
            # openDate/registerDate 누락 → None
            "astrtCont": "",  # → "내용 없음"
        }
    )
    c = _make_client(lambda r: _xml_ok(xml))
    detail = asyncio.run(c.get_patent_detail("FALLBACK-NO"))
    assert detail is not None
    assert detail.application_number == "FALLBACK-NO"
    assert detail.inventor == "정보 없음"
    assert detail.publication_date is None
    assert detail.registration_date is None
    assert detail.abstract == "내용 없음"
    assert detail.ipc_codes == []
    assert detail.application_date == ""


def test_get_patent_detail_no_items_returns_none():
    c = _make_client(lambda r: _xml_ok(_search_xml()))
    assert asyncio.run(c.get_patent_detail("nope")) is None


def test_get_patent_detail_http_error_returns_none():
    """detail 은 HTTPError 를 삼키고 None (search 와 다름)."""
    c = _make_client(lambda r: httpx.Response(503, text="down"))
    assert asyncio.run(c.get_patent_detail("x")) is None


# ── close ──────────────────────────────────────────────────────────────────────


def test_close_aclose_underlying():
    c = _make_client(lambda r: _xml_ok(""))

    async def _run():
        await c.close()
        assert c._client.is_closed

    asyncio.run(_run())


# ── get_kipris_client 싱글톤 ─────────────────────────────────────────────────────


def test_get_kipris_client_singleton():
    client_mod._kipris_client = None
    a = get_kipris_client()
    b = get_kipris_client()
    assert a is b
    assert isinstance(a, KiprisClient)
    client_mod._kipris_client = None


# ── structlog ImportError fallback (방어분기 도달) ────────────────────────────────


def test_log_falls_back_to_stdlib_when_structlog_missing(monkeypatch):
    """모듈 top 의 `except ImportError` (structlog 부재) 분기 — structlog 를 import 불가로
    만든 뒤 client 모듈을 reload 해 stdlib logging 으로 fallback 하는지 검증.

    structlog 는 설치돼 있어 정상 경로에선 도달 불가 → import 차단 후 reload 로 강제.
    """
    import builtins
    import importlib
    import logging

    real_import = builtins.__import__

    def _blocked_import(name, *args, **kwargs):
        if name == "structlog":
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked_import)
    try:
        reloaded = importlib.reload(client_mod)
        # fallback 시 log 는 stdlib Logger (이름 "kipris")
        assert isinstance(reloaded.log, logging.Logger)
        assert reloaded.log.name == "kipris"
    finally:
        monkeypatch.undo()
        importlib.reload(client_mod)  # 원복 (structlog 경로 복귀)
