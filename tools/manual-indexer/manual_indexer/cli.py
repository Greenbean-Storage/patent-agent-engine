"""CLI entry — `uv run python -m manual_indexer {extract|summarize|build|verify}`."""

from __future__ import annotations

import argparse
import sys

import structlog

from . import extract as extract_mod
from . import fetch as fetch_mod
from .paths import CACHE_DIR, RAW_ROOT, VERSION_PATH

log = structlog.get_logger()


def cmd_extract(args: argparse.Namespace) -> int:
    pdfs = fetch_mod.fetch_all(CACHE_DIR)
    meta = extract_mod.extract_all(pdfs, RAW_ROOT)
    extract_mod.write_version(meta, VERSION_PATH)
    total_tokens = sum(m["est_tokens"] for m in meta.values())
    log.info("extract.complete", parts=len(meta), total_est_tokens=total_tokens)
    return 0


def cmd_summarize(args: argparse.Namespace) -> int:
    from . import summarize as summarize_mod

    return summarize_mod.run()


def cmd_build(args: argparse.Namespace) -> int:
    rc = cmd_extract(args)
    if rc != 0:
        return rc
    return cmd_summarize(args)


def cmd_verify(args: argparse.Namespace) -> int:
    from . import paths

    if not paths.SUMMARY_PATH.exists():
        log.error("verify.no_summary", path=str(paths.SUMMARY_PATH))
        return 1
    chars = len(paths.SUMMARY_PATH.read_text(encoding="utf-8"))
    log.info("verify.ok", summary_chars=chars, est_tokens=chars // 4)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="manual-indexer")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("extract", help="Fetch PDFs + extract → raw/")
    sub.add_parser("summarize", help="raw/* → summary.md (Claude)")
    sub.add_parser("build", help="extract + summarize")
    sub.add_parser("verify", help="Check summary.md exists and report sizes")
    args = parser.parse_args(argv)

    handler = {
        "extract": cmd_extract,
        "summarize": cmd_summarize,
        "build": cmd_build,
        "verify": cmd_verify,
    }[args.cmd]
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
