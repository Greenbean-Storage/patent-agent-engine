"""CM seed CLI — FIXTURE 검증 사전에 CM 에 IOM 채워두기.

P2 Director 가 단독 IOM writer 이지만, FIXTURE mode 에서 spawn 시작 지점이 P02 가 아니면
부모 IOM 이 없어 inject_context 가 비어버린다. probe 가 그 우회를 명시적 path 옵션으로 수행.

Usage:
  make probe seed IOM=path/to/iom.json
  make probe seed IOM=path/to/iom.json INVENTION_ID=<id>
  uv run --directory tests/probe python -m probe seed --seed-iom-from path.json [--invention <id>]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import httpx

from .._common import (
    DRO_URL,
    _create_session,
    _dev_token,
    _log,
    _seed_iom,
)


async def seed(work_id_override: str | None, seed_iom_path: Path) -> int:
    async with httpx.AsyncClient() as http:
        token, user_id = await _dev_token(http)
        if work_id_override:
            work_id = work_id_override
            _log(f"using existing work_id={work_id}")
        else:
            work_id = await _create_session(http, token)
            _log(f"created new session work_id={work_id}")

        await _seed_iom(http, user_id, work_id, seed_iom_path)
        _log(f"IOM seeded from {seed_iom_path}")

        print()
        print(f"user_id      = {user_id}")
        print(f"work_id = {work_id}")
        print()
        print("Next (DRO control — 개발/검증 직접 trigger):")
        print(f"  curl -X POST {DRO_URL}/control/spawn \\")
        print(
            f'       -d \'{{"user_id":"{user_id}","work_id":"{work_id}",'
            '"persona":<N>,"pipeline_id":"<PIPELINE_ID>","chain_id":"<UUID>"}\''
        )
        return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="simulator seed")
    p.add_argument(
        "--seed-iom-from",
        type=Path,
        required=True,
        help="IOM JSON 파일 경로 (fixture/echo mode 한정 우회)",
    )
    p.add_argument(
        "--invention",
        "--invention-id",
        dest="invention",
        default=None,
        help="기존 work_id 사용. 생략 시 신규 session 생성",
    )
    p.add_argument(
        "--user",
        dest="user",
        default=None,
        help="(현재 미사용 — dev-token 이 user 결정)",
    )
    args = p.parse_args(argv)
    return asyncio.run(seed(args.invention, args.seed_iom_from))


if __name__ == "__main__":
    sys.exit(main())
