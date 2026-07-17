"""⑧ KIPI CPC — Korean parallel labels for CPC codes.

Source: https://cls.kipro.or.kr/cpc

Same crawl policy as kipi_ipc.
"""

from __future__ import annotations

from pathlib import Path

import httpx

SOURCE_ID = "kipi_cpc"
SOURCE_URL = "https://cls.kipro.or.kr/cpc"


def fetch(cache_dir: Path, http: httpx.Client) -> Path:
    raise NotImplementedError("KIPI CPC crawler — see TODO(impl)")


def parse(raw_path: Path) -> dict[str, dict]:
    """Return mapping `code → { title_ko, definition_ko }`."""
    raise NotImplementedError("KIPI CPC parser — see TODO(impl)")
