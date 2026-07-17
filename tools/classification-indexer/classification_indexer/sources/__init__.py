"""Source fetchers — one module per upstream data source.

Each module exposes:
    SOURCE_ID: str       # short identifier used in version.json
    SOURCE_URL: str      # canonical upstream URL (for attribution)
    fetch(cache_dir: Path, http: httpx.Client) -> Path  # download raw, return cache path
    parse(raw_path: Path) -> dict                       # parse raw → structured dict

The fetch step is idempotent (re-uses cached file if present unless --no-cache).
"""
