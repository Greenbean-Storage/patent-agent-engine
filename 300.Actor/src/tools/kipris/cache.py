"""검색 결과 캐시 모듈.

KIPRIS 검색 결과만 캐시 (LLM 분석 단계는 매번 새로 실행 — 결정적 일관성 유지).
캐시 키는 검색에 영향을 주는 모든 파라미터를 포함하여 '완전히 동일한 검색'에만 hit.
"""

import hashlib

from cachetools import TTLCache


class ContextCache:
    """검색 결과 캐시.

    KIPRIS API 호출 결과만 캐시한다. 키는 (query + max_results + year_range)의
    조합 해시이므로 같은 query라도 max_results 또는 year_range가 다르면 별도 항목.
    LLM 분석은 캐시하지 않음 (생각하는 부분은 매번 새로 실행).
    """

    def __init__(
        self,
        max_size: int | None = None,
        ttl: int | None = None,
    ):
        from ... import engine_config

        ccfg = engine_config.tools()["kipris"]["cache"]
        self._max_size = max_size or int(ccfg["max_size"])
        self._ttl = ttl or int(ccfg["ttl_s"])

        self._search_cache: TTLCache = TTLCache(
            maxsize=self._max_size,
            ttl=self._ttl,
        )

        self._hits = 0
        self._misses = 0

    @staticmethod
    def _make_search_key(query: str, max_results: int, year_range: int) -> str:
        """검색에 영향을 주는 모든 파라미터를 포함한 캐시 키.

        같은 query라도 max_results / year_range가 다르면 다른 결과 → 다른 키.
        query는 lower + strip으로 minor 차이 흡수 (대소문자, 좌우 공백).
        """
        normalized = f"{query.lower().strip()}|max={max_results}|year={year_range}"
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

    # =========================================================================
    # 검색 결과 캐시
    # =========================================================================

    def get_search(
        self,
        query: str,
        *,
        max_results: int,
        year_range: int,
    ) -> list[dict] | None:
        """완전히 동일한 검색만 hit. (query, max_results, year_range) 일치 필요."""
        key = self._make_search_key(query, max_results, year_range)
        result = self._search_cache.get(key)
        if result is not None:
            self._hits += 1
            return result
        self._misses += 1
        return None

    def set_search(
        self,
        query: str,
        results: list[dict],
        *,
        max_results: int,
        year_range: int,
    ) -> None:
        key = self._make_search_key(query, max_results, year_range)
        self._search_cache[key] = results

    # =========================================================================
    # 유틸리티
    # =========================================================================

    def clear(self) -> None:
        """전체 캐시 클리어."""
        self._search_cache.clear()
        self._hits = 0
        self._misses = 0

    @property
    def stats(self) -> dict:
        """캐시 통계."""
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0.0
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(hit_rate, 3),
            "search_cache_size": len(self._search_cache),
        }


# 전역 캐시 인스턴스
_cache: ContextCache | None = None


def get_cache() -> ContextCache:
    """캐시 싱글톤."""
    global _cache
    if _cache is None:
        _cache = ContextCache()
    return _cache
