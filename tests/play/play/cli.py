"""play track CLI — pipeline 실행 (dispatch chain BFS follow).

stack MODE 자동 감지 (@deployment/profile.stack.yaml) — FIXTURE 일 때만 invariants check 자동 호출.
PRODUCTION 일 때는 skip. 수동 `--fixture/--no-fixture` flag 없음.

dispatch_to 에 따라 spawn 된 후속 chain (P02→P03 등) 자연 BFS follow.

사용법:
  uv run python -m play                 # 無인자 = root pipeline 전수 (fixture 보유 *.R00.* 순차 + 집계)
  uv run python -m play P03.R00         # 단일
  uv run python -m play P03.R00 --seed-iom-from path.json --ws-timeout 1800
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from play._run import detect_stack_mode, run_pipeline


def _find_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "@pipelines").is_dir():
            return parent
    raise FileNotFoundError("Cannot locate project root")


ROOT = _find_root()
DEFAULT_FIXTURE_IOM = ROOT / "tests" / "data" / "iom-samples" / "smart_beverage_detailed.json"


def _resolve_fixture_mode() -> bool:
    """stack 의 LLM 모드 감지 (@deployment/profile.stack.yaml). FIXTURE 이면 True (invariants 자동)."""
    mode = detect_stack_mode()
    if mode == "PRODUCTION":
        print("[play] stack MODE=PRODUCTION → invariants check skip")
        return False
    if mode == "FIXTURE":
        print("[play] stack MODE=FIXTURE → invariants check 자동")
        return True
    # UNKNOWN — fixture 가정 (보수적 default)
    print(f"[play] stack MODE={mode} → fixture 가정")
    return True


def _root_pipelines() -> list[str]:
    """전수 대상 root pipeline — fixture 보유 `*.R00.*` (하위 chain 은 dispatch 로 자동 커버)."""
    fixtures = ROOT / "tests" / "data" / "llm-fixtures"
    return sorted(d.name for d in fixtures.iterdir() if d.is_dir() and ".R00." in d.name)


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="play",
        description="검증 track 6 — pipeline 실행 (無인자 = root 전수, dispatch chain BFS follow)",
    )
    ap.add_argument(
        "pipeline_id",
        nargs="?",
        default=None,
        help="예: P03.R00 또는 P03.R00.PRIOR_ART_SEARCH_ANALYZE. 생략 = root 전수",
    )
    ap.add_argument(
        "--seed-iom-from",
        type=Path,
        default=None,
        help="IOM JSON 사전 적재 (probe seed 라이브러리 호출)",
    )
    ap.add_argument(
        "--ws-timeout",
        type=float,
        default=1800.0,
        help="Trail polling timeout (sec, default 1800)",
    )
    args = ap.parse_args()

    fixture = _resolve_fixture_mode()

    # fixture mode + SEED 미지정 → default fixture IOM 자동 seed (probe seed 라이브러리 호출)
    seed_path = args.seed_iom_from
    if fixture and seed_path is None and DEFAULT_FIXTURE_IOM.exists():
        seed_path = DEFAULT_FIXTURE_IOM
        print(f"[play] fixture mode + SEED 미지정 → default IOM 자동 seed: {seed_path.name}")

    targets = [args.pipeline_id] if args.pipeline_id else _root_pipelines()
    if not targets:
        print("[play] 전수 대상 root pipeline 없음 (tests/data/llm-fixtures/*.R00.*)")
        return 2
    if len(targets) > 1:
        print(f"[play] root 전수 모드 — {len(targets)} pipelines: {', '.join(targets)}")

    results: list[tuple[str, int]] = []
    for pid in targets:
        rc = asyncio.run(
            run_pipeline(
                pid,
                fixture_mode=fixture,
                ws_timeout=args.ws_timeout,
                seed_iom_path=seed_path,
            )
        )
        results.append((pid, rc))

    if len(results) > 1:
        print("=" * 60)
        print("  play 전수 집계")
        print("=" * 60)
        for pid, rc in results:
            print(f"  {'PASS' if rc == 0 else 'FAIL'}  {pid}")
        print("=" * 60)
    return 0 if all(rc == 0 for _, rc in results) else 1
