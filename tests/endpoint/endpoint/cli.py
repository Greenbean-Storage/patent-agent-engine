"""endpoint track CLI — 외부 API (REST + WS) contract e2e.

사용법:
  uv run python -m endpoint                       # 모든 phase
  uv run python -m endpoint health                # 단일 phase
  uv run python -m endpoint ws_tape --tape P01.R00.CHAT_CONVERSATION/02-rt-error-message
  uv run python -m endpoint call --rest "GET /api/v1/info/providers"   # 단건 호출 UI

phase 명은 도메인 객체 그대로 (legacy_* / deprecated_* 잔재 명명 없음). 현행 phase = `_ALL_PHASES`.
ws_tape 는 dro:fake 전용 (dro:real 스택에선 skip-pass). call 은 탐색/디버그용 단건 전송.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from venezia_topology import service_url

from .phases import all_phases

_ALL_PHASES = [
    # 새 트리 (info/user/works). OPEN 모드 기준.
    "health",
    "info",
    "account",
    "works",
    "auth",
    "work_resources",
    "output",  # output/draft build·preview·download + proposal 501
    "ws",
    "ws_tape",  # dro:fake 전용 포괄 tape suite (dro:real 이면 skip-pass)
    "error_envelope",
    "secure",  # SECURE 전용 (OPEN 이면 skip)
]


def main() -> int:
    p = argparse.ArgumentParser(
        prog="endpoint",
        description="검증 track 7 — 외부 API REST + WS contract e2e",
    )
    p.add_argument(
        "--dro-url",
        default=service_url("dro"),
        help="DRO production 포트 URL",
    )
    p.add_argument(
        "--token",
        default=None,
        help="SECURE 모드 JWT (미지정 시 EP_TOKEN env, 그래도 없으면 SECURE 에서 mint)",
    )
    p.add_argument("--tape", default=None, help="ws_tape 단일 모드 — <pipeline>/<tape명>")
    p.add_argument("--rest", default=None, help='call: REST 1건 — "METHOD /path"')
    p.add_argument("--ws", default=None, help="call: WS 1건 — '<action> {json}'")
    p.add_argument("--body", default=None, help="call: 요청 body JSON")
    p.add_argument(
        "phases",
        nargs="*",
        choices=[*_ALL_PHASES, "all", "call"],
        default=["all"],
        help="실행할 phase (positional, 여러 개) | call = 단건 호출 UI. 미지정 시 all",
    )
    args = p.parse_args()

    selected = args.phases if args.phases else ["all"]
    if "call" in selected:
        from .call import run_call  # noqa: PLC0415

        return run_call(args.rest, args.ws, args.body)
    if "all" in selected:
        selected = _ALL_PHASES

    return asyncio.run(all_phases.run_all(args.dro_url, selected, token=args.token, tape=args.tape))


if __name__ == "__main__":
    sys.exit(main())
