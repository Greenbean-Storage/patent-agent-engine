"""⑨ WIPO IPC-CPC Concordance — IPC ↔ CPC code mapping.

Reference: https://www.wipo.int/classifications/ipc/ (concordance file in
the publications package).

Used for cross-validation — when the LLM picks IPC codes, verify that
the corresponding CPC codes (via concordance) overlap with what the LLM
picked for CPC.
"""

from __future__ import annotations

from pathlib import Path

import httpx

SOURCE_ID = "ipc_cpc_concordance"
SOURCE_URL = "https://www.wipo.int/classifications/ipc/"


def fetch(cache_dir: Path, http: httpx.Client) -> Path:
    raise NotImplementedError("Concordance fetcher — see TODO(impl)")


def parse(raw_path: Path) -> dict:
    """Return { 'ipc_to_cpc': {'A47G 19/22': ['A47G 19/2277', ...]},
    'cpc_to_ipc': {...} }"""
    raise NotImplementedError("Concordance parser — see TODO(impl)")
