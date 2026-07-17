"""KIPRIS 검색 캐시 전수 (invoke 단위) — 300.Actor/src/tools/kipris/cache.py.

대상: ContextCache (TTLCache wrapper) + get_cache 싱글톤.
검증 포인트(진짜 assert):
  - _make_search_key: query lower/strip 정규화 + max_results/year_range 가 키에 반영 →
    같은 query 라도 파라미터가 다르면 다른 키, 대소문자/공백 차이는 흡수.
  - get_search miss → None + misses 증가 / set_search 후 hit → 동일 results + hits 증가.
  - 파라미터(max_results / year_range) 불일치 = miss.
  - TTL 만료 → 만료된 항목은 miss (monotonic timer monkeypatch 로 시간 전진).
  - clear() 가 cache + hits/misses 리셋.
  - stats 의 hit_rate 계산 (total 0 일 때 0.0, 일반).
  - 생성자 default (settings) vs 명시 인자.
  - get_cache 싱글톤 동일 인스턴스.

async 없음 (전부 동기). TTLCache 내부 timer 를 monkeypatch 해 만료를 결정적으로 유발.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "300.Actor"))
sys.path.insert(0, str(ROOT / "shared"))

from src.tools.kipris import cache as cache_mod  # noqa: E402
from src.tools.kipris.cache import ContextCache, get_cache  # noqa: E402


# ── _make_search_key ────────────────────────────────────────────────────────────


def test_make_search_key_is_deterministic_16_hex():
    k = ContextCache._make_search_key("robot arm", 10, 5)
    assert k == ContextCache._make_search_key("robot arm", 10, 5)
    assert len(k) == 16
    assert all(ch in "0123456789abcdef" for ch in k)


def test_make_search_key_normalizes_case_and_whitespace():
    """query 는 lower + strip 으로 minor 차이 흡수 → 같은 키."""
    a = ContextCache._make_search_key("  Robot ARM  ", 10, 5)
    b = ContextCache._make_search_key("robot arm", 10, 5)
    assert a == b


def test_make_search_key_differs_on_max_results():
    a = ContextCache._make_search_key("q", 10, 5)
    b = ContextCache._make_search_key("q", 20, 5)
    assert a != b


def test_make_search_key_differs_on_year_range():
    a = ContextCache._make_search_key("q", 10, 5)
    b = ContextCache._make_search_key("q", 10, 0)
    assert a != b


# ── get/set (hit / miss) ─────────────────────────────────────────────────────────


def test_get_search_miss_returns_none_and_counts():
    c = ContextCache(max_size=8, ttl=100)
    assert c.get_search("nope", max_results=10, year_range=5) is None
    assert c.stats["misses"] == 1
    assert c.stats["hits"] == 0


def test_set_then_get_hit_returns_same_results_and_counts():
    c = ContextCache(max_size=8, ttl=100)
    payload = [{"application_number": "10-1", "title": "T"}]
    c.set_search("q", payload, max_results=10, year_range=5)
    got = c.get_search("q", max_results=10, year_range=5)
    assert got == payload
    assert c.stats["hits"] == 1
    assert c.stats["misses"] == 0
    assert c.stats["search_cache_size"] == 1


def test_get_hit_uses_normalized_key():
    """set 은 정규화 전 query, get 은 대소문자/공백 다른 query 라도 같은 항목 hit."""
    c = ContextCache(max_size=8, ttl=100)
    payload = [{"application_number": "10-2"}]
    c.set_search("Robot Arm", payload, max_results=10, year_range=5)
    got = c.get_search("  robot arm ", max_results=10, year_range=5)
    assert got == payload


def test_param_mismatch_is_miss():
    c = ContextCache(max_size=8, ttl=100)
    c.set_search("q", [{"a": 1}], max_results=10, year_range=5)
    # year_range 다름 → 다른 키 → miss
    assert c.get_search("q", max_results=10, year_range=0) is None
    # max_results 다름 → 다른 키 → miss
    assert c.get_search("q", max_results=20, year_range=5) is None
    assert c.stats["misses"] == 2


# ── TTL 만료 ──────────────────────────────────────────────────────────────────────


def test_ttl_expiry_makes_entry_miss():
    """TTLCache 를 custom timer 로 교체 — set 후 ttl 초과로 시간 전진하면 miss.

    cachetools 의 `timer` 는 read-only property 라 setattr 불가 → 생성자 인자로 주입한
    TTLCache 를 instance 의 _search_cache 에 직접 swap (속성 자체는 rebind 가능).
    """
    from cachetools import TTLCache

    clock = {"t": 1000.0}
    c = ContextCache(max_size=8, ttl=30)
    c._search_cache = TTLCache(maxsize=8, ttl=30, timer=lambda: clock["t"])

    c.set_search("q", [{"a": 1}], max_results=10, year_range=5)
    # ttl 직전 — 아직 hit
    clock["t"] = 1000.0 + 29
    assert c.get_search("q", max_results=10, year_range=5) == [{"a": 1}]
    # ttl 초과 — 만료 → miss
    clock["t"] = 1000.0 + 31
    assert c.get_search("q", max_results=10, year_range=5) is None


# ── clear ──────────────────────────────────────────────────────────────────────


def test_clear_resets_cache_and_counters():
    c = ContextCache(max_size=8, ttl=100)
    c.set_search("q", [{"a": 1}], max_results=10, year_range=5)
    c.get_search("q", max_results=10, year_range=5)  # hit
    c.get_search("z", max_results=10, year_range=5)  # miss
    assert c.stats["search_cache_size"] == 1
    c.clear()
    assert c.stats["search_cache_size"] == 0
    assert c.stats["hits"] == 0
    assert c.stats["misses"] == 0


# ── stats / hit_rate ─────────────────────────────────────────────────────────────


def test_stats_hit_rate_zero_when_no_lookups():
    c = ContextCache(max_size=8, ttl=100)
    assert c.stats["hit_rate"] == 0.0
    assert c.stats == {
        "hits": 0,
        "misses": 0,
        "hit_rate": 0.0,
        "search_cache_size": 0,
    }


def test_stats_hit_rate_computed_and_rounded():
    c = ContextCache(max_size=8, ttl=100)
    c.set_search("q", [{"a": 1}], max_results=10, year_range=5)
    c.get_search("q", max_results=10, year_range=5)  # hit  (1)
    c.get_search("q", max_results=10, year_range=5)  # hit  (2)
    c.get_search("miss", max_results=10, year_range=5)  # miss (1)
    s = c.stats
    assert s["hits"] == 2
    assert s["misses"] == 1
    # 2 / 3 = 0.6667 → round(.,3) = 0.667
    assert s["hit_rate"] == 0.667


# ── 생성자 default vs 명시 ────────────────────────────────────────────────────────


def test_init_uses_engine_config_defaults_when_none():
    from src import engine_config

    ccfg = engine_config.tools()["kipris"]["cache"]
    c = ContextCache()
    assert c._max_size == ccfg["max_size"]
    assert c._ttl == ccfg["ttl_s"]
    assert c._search_cache.maxsize == ccfg["max_size"]
    assert c._search_cache.ttl == ccfg["ttl_s"]


def test_init_uses_explicit_args():
    c = ContextCache(max_size=3, ttl=7)
    assert c._max_size == 3
    assert c._ttl == 7
    assert c._search_cache.maxsize == 3
    assert c._search_cache.ttl == 7


# ── get_cache 싱글톤 ─────────────────────────────────────────────────────────────


def test_get_cache_singleton():
    cache_mod._cache = None
    a = get_cache()
    b = get_cache()
    assert a is b
    assert isinstance(a, ContextCache)
    cache_mod._cache = None
