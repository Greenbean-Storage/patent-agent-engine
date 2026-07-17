"""Extract text from KIPO 심사기준 PDFs → markdown.

Uses `pypdf` (pure-python, no system deps). Per-page text is concatenated;
common headers/footers (page number, repeated chapter title) are stripped
heuristically — lines that appear on >50% of pages are dropped.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections import Counter
from pathlib import Path

import structlog
from pypdf import PdfReader

from .paths import PART_TITLES, PARTS, RAW_ROOT

log = structlog.get_logger()


SOURCE_URL_BASE = (
    "https://www.kipo.go.kr/upload/mobile/exammanual/pdf/exammanual_{part}.pdf"
)


def extract_pdf(pdf_path: Path) -> tuple[str, int]:
    """Extract page-by-page text + strip common page boilerplate.

    Returns (clean_text, page_count).
    """
    reader = PdfReader(str(pdf_path))
    pages_text = [(p.extract_text() or "").strip() for p in reader.pages]
    n_pages = len(pages_text)

    # Heuristic: lines that appear on >50% of pages are likely page header/footer.
    line_pages: Counter[str] = Counter()
    for text in pages_text:
        unique_lines = set()
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or len(stripped) > 80:
                continue
            unique_lines.add(stripped)
        for line in unique_lines:
            line_pages[line] += 1

    threshold = max(2, n_pages // 2)
    boilerplate = {ln for ln, count in line_pages.items() if count >= threshold}

    # Strip page-number-only lines and boilerplate lines
    cleaned_pages: list[str] = []
    for text in pages_text:
        kept_lines: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                kept_lines.append("")
                continue
            if stripped in boilerplate:
                continue
            # Pure-numeric or "- 1 -" style page numbers
            if re.fullmatch(r"-?\s*\d{1,4}\s*-?", stripped):
                continue
            kept_lines.append(line)
        page_text = "\n".join(kept_lines).strip()
        if page_text:
            cleaned_pages.append(page_text)

    return "\n\n".join(cleaned_pages), n_pages


def extract_part_to_markdown(part: str, pdf_path: Path) -> str:
    """Build the full markdown body for one Part."""
    text, n_pages = extract_pdf(pdf_path)
    title = PART_TITLES.get(part, "")
    url = SOURCE_URL_BASE.format(part=part)
    extracted_at = dt.datetime.now(dt.UTC).isoformat()
    frontmatter = (
        f"---\n"
        f'source: "KIPO 심사기준 Part {part} — {title}"\n'
        f'url: "{url}"\n'
        f'license: "KOGL 2.0"\n'
        f"pages: {n_pages}\n"
        f'extracted_at: "{extracted_at}"\n'
        f"---\n\n"
        f"# Part {part} — {title}\n\n"
    )
    return frontmatter + text + "\n"


def extract_all(pdfs: dict[str, Path], out_root: Path = RAW_ROOT) -> dict[str, dict]:
    """Extract every PDF → @knowledge/drafting/raw/exammanual_{part}.md.

    Returns metadata per part: {part: {bytes, pages, chars, est_tokens}}.
    """
    out_root.mkdir(parents=True, exist_ok=True)
    meta: dict[str, dict] = {}
    for part in PARTS:
        pdf_path = pdfs[part]
        log.info("extract.start", part=part, pdf=str(pdf_path))
        body = extract_part_to_markdown(part, pdf_path)
        dest = out_root / f"exammanual_{part}.md"
        dest.write_text(body, encoding="utf-8")
        chars = len(body)
        meta[part] = {
            "bytes": dest.stat().st_size,
            "chars": chars,
            "est_tokens": chars // 4,  # Korean rough estimate
        }
        log.info("extract.done", part=part, **meta[part])
    return meta


def write_version(meta: dict[str, dict], out_path: Path) -> None:
    """Write @knowledge/drafting/version.json."""
    payload = {
        "schema_version": "1.0.0",
        "source": "KIPO 심사기준",
        "source_url_base": SOURCE_URL_BASE,
        "license": "KOGL 2.0",
        "extracted_at": dt.datetime.now(dt.UTC).isoformat(),
        "parts": {p: {"title": PART_TITLES[p], **meta[p]} for p in PARTS},
        "total_chars": sum(m["chars"] for m in meta.values()),
        "total_est_tokens": sum(m["est_tokens"] for m in meta.values()),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
