"""③ KIPI IPC — Korean parallel labels for IPC codes.

Source: https://cls.kipro.or.kr/api/ipc/search/listByText (POST JSON)

Crawl policy (verified 2026-05-04):
- robots.txt: User-agent: * / Allow: /
- 1-second sleep between requests
- User-Agent identifies us
- Extract only factual classification metadata (codes + Korean labels);
  do not copy site design or commentary.

API behavior:
- POST body: `{"searchText": "<text>", "page": <int>, "size": 500}`
- Response: `{ size, page, totalPages, totalElements, list: [<node>...] }`
- Each node has `id`, `code`, `level`, `korTitle`, `korNote`, `korGuide`, `nodes`.
- Querying with a section letter (`A`, `B`, ...) yields the entire section
  tree; pagination is needed for large sections (size=500 per page).

Fetch strategy:
- For each section A-H: query that section letter, walk all pages, accumulate.
- Walk the resulting forest depth-first, extract `{normalized_code: {...}}`.
- Strip HTML from korTitle/korGuide (KIPI ships <span class="explanation">…
  </span> markup inside the labels).

Normalization:
- KIPI returns codes like `A01B1/00` (no space). IPC standard is `A01B 1/00`.
  We emit the spaced form to match wipo_ipc output.
"""

from __future__ import annotations

import html
import json
import re
import time
from pathlib import Path
from typing import Any

import httpx
import structlog

log = structlog.get_logger()

SOURCE_ID = "kipi_ipc"
SOURCE_URL = "https://cls.kipro.or.kr/api/ipc/search/listByText"

SECTIONS = list("ABCDEFGH")
_PAGE_SIZE = 500
_REQUEST_INTERVAL_S = 1.0
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 "
    "(venezia-classification-indexer/0.1)"
)
_REFERER = "https://cls.kipro.or.kr/classification/ipc/search"
_ORIGIN = "https://cls.kipro.or.kr"


def fetch(cache_dir: Path, http: httpx.Client) -> Path:
    """Crawl KIPI IPC sections → cached JSON of `{code: {title_ko, definition_ko}}`.
    Re-uses cache if present.
    """
    raw_dir = cache_dir / SOURCE_ID
    raw_dir.mkdir(parents=True, exist_ok=True)

    for section in SECTIONS:
        page = 0
        while True:
            page_path = raw_dir / f"{section}_p{page}.json"
            if page_path.exists() and page_path.stat().st_size > 100:
                # already cached — peek to see if more pages
                data = json.loads(page_path.read_text(encoding="utf-8"))
            else:
                payload = {"searchText": section, "page": page, "size": _PAGE_SIZE}
                log.info("kipi_ipc.fetch", section=section, page=page)
                r = http.post(
                    SOURCE_URL,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/plain, */*",
                        "Origin": _ORIGIN,
                        "Referer": _REFERER,
                        "User-Agent": _USER_AGENT,
                    },
                    timeout=60.0,
                )
                r.raise_for_status()
                data = r.json()
                page_path.write_text(
                    json.dumps(data, ensure_ascii=False),
                    encoding="utf-8",
                )
                time.sleep(_REQUEST_INTERVAL_S)
            total_pages = data.get("totalPages", 1)
            page += 1
            if page >= total_pages:
                break

    merged_path = cache_dir / f"{SOURCE_ID}.json"
    if not merged_path.exists():
        mapping = parse(raw_dir)
        merged_path.write_text(
            json.dumps(mapping, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        log.info("kipi_ipc.parse.cached", path=str(merged_path), codes=len(mapping))
    return merged_path


_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(s: str | None) -> str | None:
    if not s:
        return s
    out = _TAG_RE.sub("", s)
    out = html.unescape(out)
    out = re.sub(r"\s+", " ", out).strip()
    return out or None


_PACKED_GROUP = re.compile(r"^([A-HY]\d{2}[A-Z])(\d+)/(\d+)$")
_PACKED_GROUP_STAR = re.compile(r"^([A-HY]\d{2}[A-Z])(\d+)/(\d+)\*$")


def _normalize_code(code: str) -> tuple[str, bool]:
    """KIPI 'A01B1/00' or 'A01B1/00*' → standard 'A01B 1/00'.

    Returns (normalized, is_star). The trailing '*' marks a "main group with
    children" duplicate node; we de-dupe later by preferring the non-star form.
    Section/Class/Subclass codes pass through unchanged.
    """
    m = _PACKED_GROUP_STAR.match(code)
    if m:
        return f"{m.group(1)} {int(m.group(2))}/{m.group(3)}", True
    m = _PACKED_GROUP.match(code)
    if m:
        return f"{m.group(1)} {int(m.group(2))}/{m.group(3)}", False
    return code, False


def parse(raw_path: Path) -> dict[str, dict]:
    """Parse cached page files → `{code: {title_ko, definition_ko}}`.

    If raw_path is the cached merged JSON, return it directly.
    """
    if raw_path.is_file():
        return json.loads(raw_path.read_text(encoding="utf-8"))

    mapping: dict[str, dict] = {}

    for page_file in sorted(raw_path.glob("*_p*.json")):
        data = json.loads(page_file.read_text(encoding="utf-8"))
        _walk(data.get("list") or [], mapping)

    return mapping


def _walk(nodes: list[dict[str, Any]], mapping: dict[str, dict]) -> None:
    for n in nodes:
        raw_code = n.get("code") or n.get("id") or ""
        if raw_code:
            normalized, is_star = _normalize_code(raw_code)
            title_ko = _strip_html(n.get("korTitle"))
            definition_ko = _strip_html(n.get("korGuide")) or _strip_html(
                n.get("korNote")
            )
            existing = mapping.get(normalized)
            # Prefer non-star (more concrete) over star duplicate.
            if existing is None or (existing.get("_star") and not is_star):
                entry: dict[str, Any] = {}
                if title_ko:
                    entry["title_ko"] = title_ko
                if definition_ko:
                    entry["definition_ko"] = definition_ko
                if entry:
                    if is_star:
                        entry["_star"] = True
                    mapping[normalized] = entry
        if n.get("nodes"):
            _walk(n["nodes"], mapping)
