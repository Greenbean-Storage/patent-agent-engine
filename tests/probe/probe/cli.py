"""probe track CLI — 실 CM 블랙박스 도구 (관찰/구성/제어 + 검증 게이트).

[관찰/구성/제어]
probe view <chain_id>            chain 전체 (RT + trail + IOM + drawings) 표시
probe trail <chain_id>           trail.jsonl 만 stream
probe check <chain_id>           9 invariants 정합 검사
probe seed --iom <path>          IOM JSON CM 적재
probe list [--user <id>]         세션·invention 목록 (IOM /fields/title pointer fetch)
probe list-chains <work_id> invention 의 chain 인벤토리
probe dump-rt <chain> <rt>       RT JSON export (debugging)
probe models <work_id>      4 모델 (IOM/CMM/CDS/UR) dump — `--pointer` 로 부분 read
probe dialogs <work_id>     페르소나별 누적 dialog dump (P-A v3 layout)
probe clean <work_id>       invention 삭제 (DELETE)
[검증 게이트] (라인-커버리지 아님 — 그건 invoke 트랙)
probe exercise                   CM 의 모든 API 전수 호출 (실 CM 블랙박스)
probe structure <work_id>   세션 S3 구조 ↔ scaffolding + manifest 대조 검증
probe verify                     게이트 = CM API 전수 + scaffolding 99% (임시 세션, mode-agnostic)

옛 `probe contexts` 는 P-A v1 의 contexts/ namespace 폐기와 함께 제거.
대체: `probe models` (cm:// resource — pointer 지원) + `probe dialogs` (페르소나 누적).
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from ._common import CM_URL, OPEN_USER_ID
from .commands import check as check_cmd
from .commands import clean as clean_cmd
from .commands import dialogs as dialogs_cmd
from .commands import dump_rt as dump_rt_cmd
from .commands import exercise as exercise_cmd
from .commands import list as list_cmd
from .commands import list_chains as list_chains_cmd
from .commands import models as models_cmd
from .commands import seed as seed_cmd
from .commands import structure as structure_cmd
from .commands import trail as trail_cmd
from .commands import verify as verify_cmd
from .commands import view as view_cmd


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="probe",
        description="검증 track 4 — CM 관찰/구성/제어 (검증 환경 라이브러리)",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_view = sub.add_parser("view", help="chain 전체 (RT + trail + IOM + drawings) 표시")
    p_view.add_argument("chain_id")
    p_view.add_argument("--user-id", default=OPEN_USER_ID)
    p_view.add_argument("--invention-id", default=None)
    p_view.add_argument("--cm-url", default=CM_URL)
    p_view.add_argument("-v", "--verbose", action="store_true")

    p_trail = sub.add_parser("trail", help="trail.jsonl 만 stream")
    p_trail.add_argument("chain_id")
    p_trail.add_argument("--user-id", default=OPEN_USER_ID)
    p_trail.add_argument("--invention-id", required=True)
    p_trail.add_argument("--cm-url", default=CM_URL)

    p_check = sub.add_parser("check", help="9 invariants 정합 검사 (fixture mode chain)")
    p_check.add_argument("chain_id")
    p_check.add_argument("--user-id", default=OPEN_USER_ID)
    p_check.add_argument("--invention-id", required=True)
    p_check.add_argument("--cm-url", default=CM_URL)

    p_seed = sub.add_parser("seed", help="IOM JSON 을 CM 에 PUT")
    p_seed.add_argument("--iom", required=True, type=Path, help="IOM JSON 파일 경로")
    p_seed.add_argument("--invention", default=None, help="기존 work_id (생략 시 신규)")

    p_list = sub.add_parser("list", help="사용자의 세션·invention 목록")
    p_list.add_argument(
        "--user-id", default=None, help="생략 시 OPEN 고정 user_id (SECURE 면 mint sub)"
    )
    p_list.add_argument("--cm-url", default=CM_URL)

    p_list_chains = sub.add_parser("list-chains", help="invention 의 chain 인벤토리")
    p_list_chains.add_argument("work_id")
    p_list_chains.add_argument("--user-id", default=OPEN_USER_ID)
    p_list_chains.add_argument("--cm-url", default=CM_URL)

    p_dump_rt = sub.add_parser("dump-rt", help="RT JSON export (debugging)")
    p_dump_rt.add_argument("chain_id")
    p_dump_rt.add_argument("rt_id")
    p_dump_rt.add_argument("--user-id", default=OPEN_USER_ID)
    p_dump_rt.add_argument("--invention-id", required=True)
    p_dump_rt.add_argument("--cm-url", default=CM_URL)

    p_models = sub.add_parser(
        "models", help="IOM/CMM/CDS/UR dump — --pointer 로 RFC 6901 부분 read"
    )
    p_models.add_argument("work_id")
    p_models.add_argument("--user-id", default=OPEN_USER_ID)
    p_models.add_argument("--cm-url", default=CM_URL)
    p_models.add_argument("--pointer", default="", help="RFC 6901 JSON Pointer (예: /fields/title)")
    p_models.add_argument(
        "--only",
        choices=[
            "invention-object-model",
            "concept-maturity-model",
            "concept-discovery-stack",
            "user-roadmap",
        ],
        default=None,
        help="단일 모델만 dump",
    )

    p_dialogs = sub.add_parser("dialogs", help="페르소나별 누적 dialog dump (P-A v3)")
    p_dialogs.add_argument("work_id")
    p_dialogs.add_argument("--user-id", default=OPEN_USER_ID)
    p_dialogs.add_argument("--cm-url", default=CM_URL)

    p_clean = sub.add_parser("clean", help="invention 삭제 (DELETE, 되돌릴 수 없음)")
    p_clean.add_argument("work_id")
    p_clean.add_argument("--user-id", default=OPEN_USER_ID)
    p_clean.add_argument("--yes", action="store_true", help="confirm prompt skip")
    p_clean.add_argument("--cm-url", default=CM_URL)

    p_structure = sub.add_parser(
        "structure", help="세션 S3 메모리 구조를 scaffolding + manifest 와 대조 검증"
    )
    p_structure.add_argument("work_id")
    p_structure.add_argument("--user-id", default=OPEN_USER_ID)
    p_structure.add_argument("--cm-url", default=CM_URL)

    p_exercise = sub.add_parser("exercise", help="CM 의 모든 API 전수 호출 (실 CM 블랙박스)")
    p_exercise.add_argument("--user-id", default=OPEN_USER_ID)
    p_exercise.add_argument("--cm-url", default=CM_URL)

    p_verify = sub.add_parser(
        "verify",
        help="probe 게이트 — CM API 전수 + scaffolding 구조검증 (임시 세션, mode-agnostic)",
    )
    p_verify.add_argument("--user-id", default=OPEN_USER_ID)
    p_verify.add_argument("--cm-url", default=CM_URL)

    args = ap.parse_args()

    if args.cmd == "view":
        return asyncio.run(
            view_cmd.run_viewer(
                args.chain_id, args.user_id, args.work_id, args.cm_url, args.verbose
            )
        )
    if args.cmd == "trail":
        return asyncio.run(
            trail_cmd.run_trail(args.chain_id, args.user_id, args.work_id, args.cm_url)
        )
    if args.cmd == "check":
        rep = asyncio.run(
            check_cmd.verify_chain(args.user_id, args.work_id, args.chain_id, args.cm_url)
        )
        check_cmd.print_report(rep)
        return 0 if rep.ok else 1
    if args.cmd == "seed":
        return asyncio.run(seed_cmd.seed(args.invention, args.iom))
    if args.cmd == "list":
        return asyncio.run(list_cmd.run_list(args.user_id, args.cm_url))
    if args.cmd == "list-chains":
        return asyncio.run(list_chains_cmd.run_list_chains(args.user_id, args.work_id, args.cm_url))
    if args.cmd == "dump-rt":
        return asyncio.run(
            dump_rt_cmd.run_dump_rt(
                args.user_id, args.work_id, args.chain_id, args.rt_id, args.cm_url
            )
        )
    if args.cmd == "models":
        return asyncio.run(
            models_cmd.run_models(args.user_id, args.work_id, args.cm_url, args.pointer, args.only)
        )
    if args.cmd == "dialogs":
        return asyncio.run(dialogs_cmd.run_dialogs(args.user_id, args.work_id, args.cm_url))
    if args.cmd == "clean":
        return asyncio.run(
            clean_cmd.run_clean(args.user_id, args.work_id, yes=args.yes, cm_url=args.cm_url)
        )
    if args.cmd == "structure":
        return asyncio.run(structure_cmd.run_structure(args.user_id, args.work_id, args.cm_url))
    if args.cmd == "exercise":
        return asyncio.run(exercise_cmd.run_exercise(args.user_id, args.cm_url))
    if args.cmd == "verify":
        return asyncio.run(verify_cmd.run_verify(args.user_id, args.cm_url))
    return 1
