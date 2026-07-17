"""Shared HTTP helpers for all source fetchers."""

from __future__ import annotations

import time
from pathlib import Path

import httpx
import structlog

USER_AGENT = (
    "venezia-classification-indexer/0.1 (+https://github.com/anthropics/venezia)"
)
KIPI_REQUEST_INTERVAL_S = 1.0  # rate-limit self-discipline for cls.kipro.or.kr

log = structlog.get_logger()


def make_client(timeout: float = 60.0) -> httpx.Client:
    return httpx.Client(
        timeout=timeout,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    )


def download(
    http: httpx.Client,
    url: str,
    dest: Path,
    *,
    expect_min_bytes: int = 0,
) -> Path:
    """Download URL to dest. Returns dest. Raises on HTTP error or short body."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size >= expect_min_bytes:
        log.info("download.cached", url=url, dest=str(dest), bytes=dest.stat().st_size)
        return dest
    log.info("download.start", url=url, dest=str(dest))
    with http.stream("GET", url) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for chunk in r.iter_bytes(chunk_size=65536):
                f.write(chunk)
    size = dest.stat().st_size
    if size < expect_min_bytes:
        raise RuntimeError(
            f"downloaded {url} is too small: {size} < {expect_min_bytes}"
        )
    log.info("download.done", url=url, bytes=size)
    return dest


def polite_sleep(seconds: float = KIPI_REQUEST_INTERVAL_S) -> None:
    time.sleep(seconds)
