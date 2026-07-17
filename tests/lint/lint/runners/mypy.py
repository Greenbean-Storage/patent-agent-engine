"""mypy type check runner."""

from __future__ import annotations

import subprocess
from pathlib import Path

NAME = "mypy"


def run(root: Path, targets: list[str]) -> int:
    """각 target 별 mypy 호출. `<pkg>/src/` path 는 부모 디렉토리에서 호출하여
    relative import 가 동작하게 함. config 없으면 --ignore-missing-imports 로 진행.

    `__init__.py` 없는 src/ (200.DRO, 400.CM) 는 namespace package 이므로
    --namespace-packages + --explicit-package-bases 로 mypy 가 인식하게 함.
    """
    overall = 0
    for tgt in targets:
        path = root / tgt
        if not path.exists():
            print(f"━━━ [{NAME}] {tgt} skip (no path) ━━━")
            continue
        # `<pkg>/src/` 패턴은 부모 디렉토리에서 `mypy src` 호출
        if path.name == "src" and path.is_dir():
            cwd = path.parent
            arg = "src"
        else:
            cwd = root
            arg = tgt
        print(f"\n━━━ [{NAME}] {tgt} ━━━")
        cmd = [
            NAME,
            "--ignore-missing-imports",
            # 설치돼 있으나 stub 없는 3rd-party (pyyaml 등) — import-untyped 무시
            # (--ignore-missing-imports 는 import-not-found 만 커버).
            "--disable-error-code=import-untyped",
            "--namespace-packages",
            "--explicit-package-bases",
            "--exclude",
            "alembic",
            arg,
        ]
        rc = subprocess.call(cmd, cwd=cwd)
        overall = max(overall, rc)
        print(f"[{NAME}/{tgt}] → exit {rc}")
    print(f"\n[{NAME}] aggregate → exit {overall}")
    return overall
