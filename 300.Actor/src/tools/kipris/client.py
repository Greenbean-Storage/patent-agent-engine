"""KIPRIS Plus API 클라이언트.

한국 특허 검색 API를 호출합니다.
"""

from dataclasses import dataclass

# exception type only; 파싱은 아래 defusedxml 사용
from xml.etree.ElementTree import ParseError  # nosec B405

import defusedxml.ElementTree as ET
import httpx

from ...config import settings
from .cache import get_cache

try:
    import structlog

    log = structlog.get_logger("kipris")
except ImportError:  # fallback to stdlib
    import logging

    log = logging.getLogger("kipris")


@dataclass
class PatentSearchResult:
    """특허 검색 결과."""

    application_number: str  # 출원번호
    title: str  # 발명의 명칭
    applicant: str  # 출원인
    application_date: str  # 출원일
    abstract: str  # 요약
    ipc_codes: list[str]  # IPC 분류

    def to_dict(self) -> dict:
        """딕셔너리로 변환."""
        return {
            "application_number": self.application_number,
            "title": self.title,
            "applicant": self.applicant,
            "application_date": self.application_date,
            "abstract": self.abstract,
            "ipc_codes": self.ipc_codes,
        }


@dataclass
class PatentDetail:
    """특허 상세 정보."""

    application_number: str
    title: str
    applicant: str
    inventor: str
    application_date: str
    publication_date: str | None
    registration_date: str | None
    abstract: str
    claims: list[str]
    ipc_codes: list[str]

    def to_dict(self) -> dict:
        """딕셔너리로 변환."""
        return {
            "application_number": self.application_number,
            "title": self.title,
            "applicant": self.applicant,
            "inventor": self.inventor,
            "application_date": self.application_date,
            "publication_date": self.publication_date,
            "registration_date": self.registration_date,
            "abstract": self.abstract,
            "claims": self.claims,
            "ipc_codes": self.ipc_codes,
        }


class KiprisClient:
    """KIPRIS Plus API 클라이언트.

    KIPRIS Plus 공공데이터 API를 사용하여 특허 검색을 수행합니다.
    """

    def __init__(self):
        from ... import engine_config

        kcfg = engine_config.tools()["kipris"]
        self.api_key = settings.KIPRIS_API_KEY
        self.base_url = str(kcfg["base_url"])
        self._client = httpx.AsyncClient(timeout=float(kcfg["timeout_s"]))
        self._cache = get_cache()

    def _parse_xml_response(self, xml_text: str) -> list[dict]:
        """XML 응답을 파싱하여 딕셔너리 리스트로 반환."""
        try:
            root = ET.fromstring(xml_text)
            items = root.findall(".//item")
            results = []
            for item in items:
                result = {}
                for child in item:
                    result[child.tag] = child.text or ""
                results.append(result)
            return results
        except ParseError as e:
            log.warning("kipris.xml_parse_error", error=str(e))
            return []

    async def search_patents(
        self,
        query: str,
        *,
        max_results: int = 30,
        year_range: int = 10,
        use_cache: bool = True,
    ) -> list[PatentSearchResult]:
        """특허 검색.

        Args:
            query: 검색 키워드
            max_results: 최대 결과 수 (최대 500)
            year_range: 검색 년도 범위 (0~10, 0=전체)
            use_cache: 캐시 사용 여부 — 동일 (query, max_results, year_range) 조합만 hit.

        Returns:
            검색 결과 목록
        """
        # 캐시 확인 — query + max_results + year_range 모두 일치해야 hit
        if use_cache:
            cached = self._cache.get_search(query, max_results=max_results, year_range=year_range)
            if cached is not None:
                return [PatentSearchResult(**r) for r in cached]

        params = {
            "word": query,
            "year": year_range,
            "patent": "true",
            "utility": "true",
            "numOfRows": min(max_results, 500),
            "pageNo": 1,
            "ServiceKey": self.api_key,
        }

        try:
            response = await self._client.get(
                f"{self.base_url}/patUtiModInfoSearchSevice/getWordSearch",
                params=params,
            )
            response.raise_for_status()

            items = self._parse_xml_response(response.text)
            results = []
            for item in items[:max_results]:
                ipc_raw = item.get("ipcNumber", "")
                ipc_codes = [ipc_raw] if ipc_raw else []

                result = PatentSearchResult(
                    application_number=item.get("applicationNumber", ""),
                    title=item.get("inventionTitle", ""),
                    applicant=item.get("applicantName", ""),
                    application_date=item.get("applicationDate", "")[:10]
                    if item.get("applicationDate")
                    else "",
                    abstract=item.get("astrtCont", "") or "내용 없음",
                    ipc_codes=ipc_codes,
                )
                results.append(result)

            # 캐시 저장 — 같은 키 재사용
            if use_cache and results:
                self._cache.set_search(
                    query,
                    [r.to_dict() for r in results],
                    max_results=max_results,
                    year_range=year_range,
                )

            return results

        except httpx.HTTPError as e:
            log.error("kipris.search_error", query=query, error=str(e))
            raise

    async def get_patent_detail(
        self,
        application_number: str,
    ) -> PatentDetail | None:
        """특허 상세 조회.

        Args:
            application_number: 출원번호

        Returns:
            특허 상세 정보 또는 None
        """
        params = {
            "applicationNumber": application_number,
            "patent": "true",
            "utility": "true",
            "numOfRows": 1,
            "pageNo": 1,
            "ServiceKey": self.api_key,
        }

        try:
            response = await self._client.get(
                f"{self.base_url}/patUtiModInfoSearchSevice/getAdvancedSearch",
                params=params,
            )
            response.raise_for_status()

            items = self._parse_xml_response(response.text)
            if not items:
                return None

            item = items[0]
            ipc_raw = item.get("ipcNumber", "")

            return PatentDetail(
                application_number=item.get("applicationNumber", application_number),
                title=item.get("inventionTitle", ""),
                applicant=item.get("applicantName", ""),
                inventor=item.get("inventorName", "정보 없음"),
                application_date=item.get("applicationDate", "")[:10]
                if item.get("applicationDate")
                else "",
                publication_date=item.get("openDate", "")[:10] if item.get("openDate") else None,
                registration_date=item.get("registerDate", "")[:10]
                if item.get("registerDate")
                else None,
                abstract=item.get("astrtCont", "") or "내용 없음",
                # KIPRIS getAdvancedSearch는 청구항 본문 미반환 (서지정보·요약·도면·등록상태만)
                # 청구항 endpoint는 /patUtiModInfoSearchSevice/getClaimInfoSearchV3 추정
                # — 존재 확인됨
                # (200 OK 응답하지만 INVALID_REQUEST_PARAMETER_ERROR). 정확한 파라미터 명세는
                # KIPRIS Plus 공식 API 명세서(plus.kipris.or.kr 로그인 필요) 미확보.
                # 명세 확보 시 별도 호출 추가하면 됨.
                claims=[],
                ipc_codes=[ipc_raw] if ipc_raw else [],
            )

        except httpx.HTTPError as e:
            log.error("kipris.detail_error", application_number=application_number, error=str(e))
            return None

    async def close(self) -> None:
        """HTTP 클라이언트 종료."""
        await self._client.aclose()


# 전역 클라이언트 인스턴스
_kipris_client: KiprisClient | None = None


def get_kipris_client() -> KiprisClient:
    """Kipris 클라이언트 싱글톤."""
    global _kipris_client
    if _kipris_client is None:
        _kipris_client = KiprisClient()
    return _kipris_client
