"""Download KIPO 심사기준 7 PDFs to .cache/."""

from __future__ import annotations

from pathlib import Path

import httpx
import structlog

from .paths import CACHE_DIR, PARTS

log = structlog.get_logger()

SOURCE_URL = "https://www.kipo.go.kr/upload/mobile/exammanual/pdf/exammanual_{part}.pdf"
USER_AGENT = "venezia-manual-indexer/0.1"


def fetch_all(cache_dir: Path = CACHE_DIR) -> dict[str, Path]:
    """Download 7 PDFs (idempotent — re-uses cache). Returns {part: path}."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}
    with httpx.Client(
        timeout=120.0, headers={"User-Agent": USER_AGENT}, follow_redirects=True
    ) as http:
        for part in PARTS:
            url = SOURCE_URL.format(part=part)
            dest = cache_dir / f"exammanual_{part}.pdf"
            if dest.exists() and dest.stat().st_size > 1024:
                log.info("fetch.cached", part=part, bytes=dest.stat().st_size)
                out[part] = dest
                continue
            log.info("fetch.start", part=part, url=url)
            with http.stream("GET", url) as r:
                r.raise_for_status()
                with dest.open("wb") as f:
                    for chunk in r.iter_bytes(chunk_size=65536):
                        f.write(chunk)
            log.info("fetch.done", part=part, bytes=dest.stat().st_size)
            out[part] = dest
    return out
