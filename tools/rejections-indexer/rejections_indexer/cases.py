"""Layer 3 — KIPRIS 거절결정서·의견제출통지서 → Chroma sqlite 벡터 인덱스.

API 명세 (사용자 제공):
- 거절결정서:    http://plus.kipris.or.kr/openapi/rest/IntermediateDocumentREService/advancedSearchInfo
- 의견제출통지서: http://plus.kipris.or.kr/openapi/rest/IntermediateDocumentOPService/advancedSearchInfo
- 응답: <advancedSearchInfo> {indexNo, applicationNumber, sendNumber, sendDate, title, filePath}
- 거절이유 본문은 filePath의 PDF 안에 있음 → 다운로드 + pypdf로 텍스트 추출

빌드 흐름:
1. fetch_kipris_rejections — 7개 거절 키워드 × 50건 = 350건 메타 (rejection-decision 우선)
2. PDF 다운로드 → cache (rate-limit 1초 sleep)
3. pypdf로 텍스트 추출
4. Gemini text-embedding-004로 청구항·거절이유 임베딩
5. Chroma persistent client에 저장 → @knowledge/rejections/cases/chroma.sqlite
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import httpx
import structlog

import shared.venezia_secrets  # noqa: F401  side-effect: AWS Secret → env

from .paths import REJECTIONS_ROOT

log = structlog.get_logger()

CHROMA_COLLECTION_NAME = "rejection_cases"
EMBEDDING_MODEL = "gemini-embedding-001"

# 7개 거절 키워드 (rejectionContent param)
REJECTION_KEYWORDS = [
    "진보성",
    "신규성",
    "명확성",
    "기재불비",
    "식별력",
    "산업상이용가능성",
    "보정",
]

DEFAULT_PER_KEYWORD = 50  # 7 × 50 = 350 cases (1차 시범)
DEFAULT_TOP_PAGES = 1  # docsCount per request
DEFAULT_REQUEST_INTERVAL = 1.0  # rate-limit
DEFAULT_PDF_CHARS_LIMIT = 8000  # truncate per case

REST_BASE = "http://plus.kipris.or.kr/openapi/rest"
SERVICES = {
    "rejection_decision": "IntermediateDocumentREService",
    "office_action": "IntermediateDocumentOPService",
}

CACHE_DIR = REJECTIONS_ROOT.parent.parent / "tools" / "rejections-indexer" / ".cache"
CHROMA_DIR = REJECTIONS_ROOT / "cases"
META_PATH = CHROMA_DIR / "meta.json"


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------


def _load_kipris_key() -> str:
    key = os.environ.get("KIPRIS_KEY") or os.environ.get("KIPRIS_API_KEY")
    if not key:
        raise RuntimeError(
            "KIPRIS_KEY missing — set AWS_SECRET_NAME to include "
            "public-data-sources/personal, or export KIPRIS_KEY directly."
        )
    return key


# ---------------------------------------------------------------------------
# KIPRIS API
# ---------------------------------------------------------------------------


def _fetch_one_keyword(
    http: httpx.Client,
    api_key: str,
    service: str,
    keyword: str,
    docs_count: int,
) -> list[dict[str, str]]:
    """One keyword query → list of {applicationNumber, sendNumber, sendDate, title, filePath}."""
    url = f"{REST_BASE}/{service}/advancedSearchInfo"
    params = {
        "rejectionContent": keyword,
        "patent": "true",
        "utility": "false",
        "design": "false",
        "tradeMark": "false",
        "docsStart": "1",
        "docsCount": str(docs_count),
        "accessKey": api_key,
    }
    r = http.get(url, params=params, timeout=60.0)
    r.raise_for_status()
    root = ET.fromstring(r.text)
    out: list[dict[str, str]] = []
    for item in root.findall(".//advancedSearchInfo"):
        record = {
            "service": service,
            "rejection_keyword": keyword,
            "application_number": (item.findtext("applicationNumber") or "").strip(),
            "send_number": (item.findtext("sendNumber") or "").strip(),
            "send_date": (item.findtext("sendDate") or "").strip(),
            "title": (item.findtext("title") or "").strip(),
            "file_path": (item.findtext("filePath") or "").strip(),
        }
        if record["application_number"] and record["file_path"]:
            out.append(record)
    return out


def fetch_kipris_rejections(
    per_keyword: int = DEFAULT_PER_KEYWORD,
) -> list[dict[str, str]]:
    """Fetch metadata from both rejection-decision + office-action services.

    Returns deduped list (key = application_number + send_number) since same
    application can appear in both services or under multiple keywords.
    """
    api_key = _load_kipris_key()
    seen: set[tuple[str, str]] = set()
    all_records: list[dict[str, str]] = []

    with httpx.Client(timeout=60.0, follow_redirects=False) as http:
        for service_label, service_name in SERVICES.items():
            for keyword in REJECTION_KEYWORDS:
                log.info("kipris.fetch.start", service=service_label, keyword=keyword)
                try:
                    records = _fetch_one_keyword(
                        http, api_key, service_name, keyword, per_keyword
                    )
                except Exception as exc:
                    log.warning(
                        "kipris.fetch.fail",
                        service=service_label,
                        keyword=keyword,
                        error=str(exc),
                    )
                    records = []
                for r in records:
                    key = (r["application_number"], r["send_number"])
                    if key in seen:
                        continue
                    seen.add(key)
                    all_records.append(r)
                log.info(
                    "kipris.fetch.done",
                    service=service_label,
                    keyword=keyword,
                    fetched=len(records),
                    total_unique=len(all_records),
                )
                time.sleep(DEFAULT_REQUEST_INTERVAL)
    return all_records


# ---------------------------------------------------------------------------
# PDF download + extract
# ---------------------------------------------------------------------------


def _pdf_cache_path(record: dict[str, str]) -> Path:
    h = hashlib.sha1(record["file_path"].encode()).hexdigest()[:16]
    appno = record["application_number"]
    return CACHE_DIR / "pdfs" / f"{appno}_{h}.pdf"


def _download_pdf(http: httpx.Client, record: dict[str, str]) -> Path | None:
    path = _pdf_cache_path(record)
    if path.exists() and path.stat().st_size > 1024:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with http.stream("GET", record["file_path"]) as r:
            if r.status_code != 200:
                log.warning(
                    "pdf.download.bad_status",
                    status=r.status_code,
                    appno=record["application_number"],
                )
                return None
            with path.open("wb") as f:
                for chunk in r.iter_bytes(chunk_size=65536):
                    f.write(chunk)
    except Exception as exc:
        log.warning(
            "pdf.download.fail", appno=record["application_number"], error=str(exc)
        )
        return None
    if path.stat().st_size < 1024:
        path.unlink(missing_ok=True)
        return None
    return path


def _extract_pdf_text(pdf_path: Path, max_chars: int = DEFAULT_PDF_CHARS_LIMIT) -> str:
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(pdf_path))
        chunks: list[str] = []
        for page in reader.pages:
            t = (page.extract_text() or "").strip()
            if t:
                chunks.append(t)
            if sum(len(c) for c in chunks) > max_chars:
                break
        text = "\n\n".join(chunks)
    except Exception as exc:
        log.warning("pdf.extract.fail", path=str(pdf_path), error=str(exc))
        return ""
    return text[:max_chars]


# ---------------------------------------------------------------------------
# Legal basis extraction
# ---------------------------------------------------------------------------

_LAW_RE = re.compile(r"(?:특허법\s*)?제\s*(\d{1,3})\s*조(?:\s*제?\s*(\d{1,2})\s*항)?")


def _extract_legal_basis(text: str) -> str:
    matches = _LAW_RE.findall(text)
    if not matches:
        return ""
    out: list[str] = []
    seen: set[str] = set()
    for art, para in matches:
        token = f"§{art}" + (f"({para})" if para else "")
        if token not in seen:
            seen.add(token)
            out.append(token)
    return ",".join(out[:5])  # 최대 5개


# ---------------------------------------------------------------------------
# Embedding + Chroma
# ---------------------------------------------------------------------------


def _build_index(records: list[dict[str, Any]]) -> int:
    """Embed each record's `text` field and store in Chroma. Returns indexed count."""
    import chromadb
    from chromadb.config import Settings
    from google import genai

    if not records:
        log.warning("index.no_records")
        return 0

    gemini = genai.Client()  # Vertex AI via ENV (GOOGLE_GENAI_USE_VERTEXAI + ADC)
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(
        path=str(CHROMA_DIR),
        settings=Settings(anonymized_telemetry=False),
    )
    # Reset collection for clean rebuild
    try:
        client.delete_collection(name=CHROMA_COLLECTION_NAME)
    except Exception:
        pass
    collection = client.create_collection(name=CHROMA_COLLECTION_NAME)

    indexed = 0
    for rec in records:
        text = rec.get("text") or ""
        if not text or len(text) < 100:
            continue
        try:
            resp = gemini.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=text[:6000],
            )
            embedding = list(resp.embeddings[0].values)
        except Exception as exc:
            log.warning(
                "embed.fail", appno=rec.get("application_number"), error=str(exc)
            )
            continue

        meta = {
            "application_number": rec.get("application_number") or "",
            "send_number": rec.get("send_number") or "",
            "send_date": rec.get("send_date") or "",
            "title": rec.get("title") or "",
            "rejection_keyword": rec.get("rejection_keyword") or "",
            "service": rec.get("service") or "",
            "legal_basis": rec.get("legal_basis") or "",
        }
        doc_id = f"{rec['application_number']}_{rec.get('send_number', '0')}"
        collection.add(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[text[:6000]],
            metadatas=[meta],
        )
        indexed += 1
        if indexed % 25 == 0:
            log.info("index.progress", indexed=indexed, total=len(records))
    return indexed


# ---------------------------------------------------------------------------
# Top-level run
# ---------------------------------------------------------------------------


def run(per_keyword: int = DEFAULT_PER_KEYWORD) -> int:
    log.info(
        "rejections.cases.start",
        per_keyword=per_keyword,
        keywords=REJECTION_KEYWORDS,
        services=list(SERVICES.keys()),
    )

    metas = fetch_kipris_rejections(per_keyword=per_keyword)
    log.info("rejections.cases.fetched", n=len(metas))
    if not metas:
        log.error("rejections.cases.no_metas")
        return 1

    # Download + extract
    enriched: list[dict[str, Any]] = []
    with httpx.Client(timeout=120.0, follow_redirects=True) as http:
        for i, m in enumerate(metas, 1):
            pdf = _download_pdf(http, m)
            if not pdf:
                continue
            text = _extract_pdf_text(pdf)
            if not text or len(text) < 200:
                continue
            legal = _extract_legal_basis(text)
            enriched.append({**m, "text": text, "legal_basis": legal})
            if i % 25 == 0:
                log.info("pdf.progress", processed=i, kept=len(enriched))
            time.sleep(0.3)

    log.info("pdf.done", total_metas=len(metas), enriched=len(enriched))

    # Embed + index
    indexed = _build_index(enriched)
    log.info("index.done", indexed=indexed)

    # Meta json
    META_PATH.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "built_at": dt.datetime.now(dt.UTC).isoformat(),
                "kipris_keywords": REJECTION_KEYWORDS,
                "services": list(SERVICES.values()),
                "fetched_metas": len(metas),
                "enriched_with_text": len(enriched),
                "indexed_in_chroma": indexed,
                "embedding_model": EMBEDDING_MODEL,
                "collection": CHROMA_COLLECTION_NAME,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    log.info("rejections.cases.complete", indexed=indexed, meta=str(META_PATH))
    return 0
