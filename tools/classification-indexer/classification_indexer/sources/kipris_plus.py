"""④ KIPRIS Plus — IPC/CPC change history API.

Reference: https://plus.kipris.or.kr/ — already-held key (KIPRIS_API_KEY env).
Quota: 1,000 calls/month free tier.

Used for sanity-check (latest version) and supplementing Korean labels for
codes missing from KIPI crawl. NOT used as primary source.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx

SOURCE_ID = "kipris_plus"
SOURCE_URL = "https://plus.kipris.or.kr/"


def fetch(cache_dir: Path, http: httpx.Client) -> Path:
    """Fetch classification version metadata. Returns cached JSON path.

    Pulls only metadata (current versions, recent changes). Per-code Korean
    labels are gathered lazily by `lookup_ko(code)` if needed.
    """
    api_key = os.environ.get("KIPRIS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "KIPRIS_API_KEY env not set — required for kipris_plus source"
        )
    raise NotImplementedError("KIPRIS Plus fetcher — see TODO(impl)")


def parse(raw_path: Path) -> dict:
    """Return { 'ipc_version': '2026.01', 'cpc_version': '2026.02', 'changes': [...] }."""
    raise NotImplementedError("KIPRIS Plus parser — see TODO(impl)")
