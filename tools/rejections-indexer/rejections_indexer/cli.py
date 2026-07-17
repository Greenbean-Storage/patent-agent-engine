"""CLI entry — `uv run python -m rejections_indexer {summarize|verify|build}`."""

from __future__ import annotations

import argparse
import sys

import structlog

log = structlog.get_logger()


def cmd_summarize(args: argparse.Namespace) -> int:
    from . import summarize as summarize_mod

    return summarize_mod.run()


def cmd_by_section(args: argparse.Namespace) -> int:
    from . import by_section as by_section_mod

    return by_section_mod.run()


def cmd_cases(args: argparse.Namespace) -> int:
    from . import cases as cases_mod

    return cases_mod.run()


def cmd_build(args: argparse.Namespace) -> int:
    # PR-A summary + PR-B by-section. PR-C (RAG cases)는 별도.
    rc = cmd_summarize(args)
    if rc != 0:
        return rc
    return cmd_by_section(args)


def cmd_verify(args: argparse.Namespace) -> int:
    from . import paths

    if not paths.SUMMARY_PATH.exists():
        log.error("verify.no_summary", path=str(paths.SUMMARY_PATH))
        return 1
    chars = len(paths.SUMMARY_PATH.read_text(encoding="utf-8"))
    log.info("verify.ok", summary_chars=chars, est_tokens=chars // 4)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rejections-indexer")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("summarize", help="PR-A: drafting/raw → summary.md (Claude)")
    sub.add_parser(
        "by-section",
        help="PR-B: drafting + summary + IPC tree → by-section/{A..H}.md (Claude)",
    )
    sub.add_parser("cases", help="PR-C: KIPRIS 거절결정문 → Chroma sqlite 벡터 인덱스")
    sub.add_parser("build", help="summary + by-section (cases는 별도 — 무거움)")
    sub.add_parser("verify", help="Check summary.md exists and report sizes")
    args = parser.parse_args(argv)

    handler = {
        "summarize": cmd_summarize,
        "by-section": cmd_by_section,
        "cases": cmd_cases,
        "build": cmd_build,
        "verify": cmd_verify,
    }[args.cmd]
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
