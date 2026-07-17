"""lint track CLI — 4 runner orchestrator (ruff / mypy / bandit / pip-audit).

`make lint` 한 번이 포매팅·자동수정(ruff --fix + format write)·검사를 모두 수행한다.
별도 format 단계 없음 — ruff runner 가 항상 write. auto-fix 불가분만 잔여로 남아 FAIL.
"""

from __future__ import annotations

import argparse

from ._common import AUDIT_TARGETS, LINT_TARGETS, ROOT, SECURITY_TARGETS
from .runners import bandit, mypy, pip_audit, ruff


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="lint", description="검증 track 2 — 코드 정적 분석 일괄(자동수정+검사)"
    )
    ap.add_argument(
        "--runner",
        choices=["ruff", "mypy", "bandit", "pip-audit", "all"],
        default="all",
        help="특정 runner 만 실행 (default: all)",
    )
    args = ap.parse_args()

    plan = []
    if args.runner in ("ruff", "all"):
        plan.append(("ruff", lambda: ruff.run(ROOT, LINT_TARGETS)))
    if args.runner in ("mypy", "all"):
        plan.append(("mypy", lambda: mypy.run(ROOT, LINT_TARGETS)))
    if args.runner in ("bandit", "all"):
        plan.append(("bandit", lambda: bandit.run(ROOT, SECURITY_TARGETS)))
    if args.runner in ("pip-audit", "all"):
        plan.append(("pip-audit", lambda: pip_audit.run(ROOT, AUDIT_TARGETS)))

    results: dict[str, int] = {}
    for name, fn in plan:
        results[name] = fn()
        print()

    # advisory 폐지 — ruff/mypy/bandit/pip-audit 4개 모두 게이트. 전부 exit 0 이어야 PASS.
    # 각 runner 는 위 loop 에서 끝까지 실행(중간 중단 없음) 후 여기서 집계 — "툴 자체에 한계 없음".
    bar = "━" * 78
    print(bar)
    print("  lint — aggregate")
    print(bar)
    overall = 0
    for name, rc in results.items():
        mark = "✓" if rc == 0 else "✗"
        overall = max(overall, rc)
        print(f"  {mark} {name:<12}: exit {rc}")
    print(bar)
    if overall == 0:
        print("✅ lint PASS — ruff / mypy / bandit / pip-audit 모두 통과")
        return 0
    print(f"❌ lint FAIL — exit {overall} (4 runner 중 일부 실패)")
    return overall
