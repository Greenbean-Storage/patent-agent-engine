"""⑥ WIPO Catchword Index — keyword → IPC mapping (English).

Reference: WIPO IPC publications package (Catchword index PDF/XML, ~20K terms).

Auxiliary lookup: when the LLM is uncertain, the catchword index provides
a keyword-based shortcut into IPC subclasses.
"""

from __future__ import annotations

from pathlib import Path

import httpx

SOURCE_ID = "wipo_catchwords"
SOURCE_URL = "https://www.wipo.int/classifications/ipc/"


def fetch(cache_dir: Path, http: httpx.Client) -> Path:
    raise NotImplementedError("Catchword fetcher — see TODO(impl)")


def parse(raw_path: Path) -> dict:
    """Return { 'catchwords': [{ 'term': 'drinking-vessel',
    'ipc_codes': ['A47G 19/22', ...] }] }"""
    raise NotImplementedError("Catchword parser — see TODO(impl)")
