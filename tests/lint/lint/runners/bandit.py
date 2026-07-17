"""bandit code security pattern runner."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .._common import EXCLUDES

NAME = "bandit"


def run(root: Path, targets: list[str]) -> int:
    """bandit -r <paths> (recursive, quiet). .venv / __pycache__ 등 제외."""
    paths = [str(root / t) for t in targets if (root / t).exists()]
    if not paths:
        print(f"[{NAME}] no targets")
        return 0

    print(f"━━━ [{NAME}] code security pattern ━━━")
    # bandit --exclude 는 glob pattern (*/X/* 형태) 으로 path match
    exclude_arg = ",".join(f"*/{e}/*" for e in EXCLUDES)
    cmd = ["bandit", "-r", "-q", "--exclude", exclude_arg, *paths]
    rc = subprocess.call(cmd)
    print(f"\n[{NAME}] → exit {rc}")
    return rc
