"""CLI entry — `build-classification` or `uv run python -m classification_indexer`."""

from __future__ import annotations

import argparse
import sys

import structlog

from . import build
from .paths import CACHE_DIR

log = structlog.get_logger()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="classification-indexer",
        description="Build @knowledge/classification/ from multiple sources.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_build = sub.add_parser("build", help="Fetch + merge + verify + write")
    p_build.add_argument(
        "--only",
        choices=["ipc", "cpc", "all"],
        default="all",
        help="Limit scope (default: all)",
    )
    p_build.add_argument(
        "--cache",
        default=str(CACHE_DIR),
        help=f"Cache dir for downloaded raw files (default: {CACHE_DIR})",
    )
    p_build.add_argument(
        "--skip-fetch",
        action="store_true",
        help="Use cached raw files; do not download",
    )
    p_build.add_argument(
        "--dry-run",
        action="store_true",
        help="Run merge/verify but do not write to @knowledge/",
    )

    sub.add_parser("verify", help="Verify existing @knowledge/classification/")

    args = parser.parse_args(argv)

    if args.cmd == "build":
        return build.run(
            only=args.only,
            cache_dir=args.cache,
            skip_fetch=args.skip_fetch,
            dry_run=args.dry_run,
        )
    if args.cmd == "verify":
        from . import verify

        return verify.run_existing()
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
