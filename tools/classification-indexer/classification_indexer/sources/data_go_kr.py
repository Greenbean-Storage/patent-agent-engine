"""⑤ data.go.kr — KSIC-IPC linkage table.

Reference: https://www.data.go.kr/ — search for "KIPRISPlus_KSIC_IPC".
License: CC-BY-4.0 (public open data).

Provides Korean Standard Industrial Classification (KSIC) ↔ IPC mapping.
Used as auxiliary heuristic — when the user describes an industry, narrow
candidate IPC subclasses by industrial domain.
"""

from __future__ import annotations

from pathlib import Path

import httpx

SOURCE_ID = "ksic_ipc"
SOURCE_URL = "https://www.data.go.kr/"  # specific dataset URL pinned in TODO(impl)


def fetch(cache_dir: Path, http: httpx.Client) -> Path:
    """Download KSIC-IPC linkage CSV/JSON. Returns cached path."""
    raise NotImplementedError("data.go.kr KSIC-IPC fetcher — see TODO(impl)")


def parse(raw_path: Path) -> dict:
    """Return { 'mappings': [{ 'ksic': '11111', 'ksic_name_ko': '...',
    'ipc_subclasses': ['A47G', ...] }] }"""
    raise NotImplementedError("KSIC-IPC parser — see TODO(impl)")
