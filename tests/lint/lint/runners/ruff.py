"""ruff lint + format runner — 항상 write(자동수정+포매팅 적용)."""

from __future__ import annotations

import subprocess
from pathlib import Path

NAME = "ruff"


def run(root: Path, targets: list[str]) -> int:
    """`ruff check --fix` + `ruff format` — 둘 다 write 적용 (make lint 가 한 번에 수정+검사).

    auto-fix 가능분은 즉시 고치고, 불가분(E501 등)만 비-0 으로 남아 수동 수정을 유도한다.
    `make lint` 단일 명령이 포매팅·자동수정·검사를 모두 수행 (별도 format target 없음).
    """
    paths = [str(root / t) for t in targets if (root / t).exists()]
    if not paths:
        print(f"[{NAME}] no targets")
        return 0

    # --target-version py313 = ruff 0.8 이 인식하는 최신 (py314 아직 미지원).
    # 각 패키지의 [tool.ruff] target-version="py314" 는 ruff 가 못 받아들이므로 CLI 로 override.
    # E402 = module import not at top — 일부 모듈의 합법 lazy import 패턴 허용.
    common = ["--target-version", "py313"]

    print(f"━━━ [{NAME}] check --fix (write) ━━━")
    rc_check = subprocess.call(
        ["ruff", "check", "--fix", *common, "--extend-ignore", "E402", *paths]
    )

    print(f"\n━━━ [{NAME}] format (write) ━━━")
    rc_fmt = subprocess.call(["ruff", "format", *paths])

    rc = max(rc_check, rc_fmt)
    print(f"\n[{NAME}] check={rc_check} format={rc_fmt} → exit {rc}")
    return rc
