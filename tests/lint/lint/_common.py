"""lint 공통 — root 탐지, 대상 경로/제외 패턴."""

from __future__ import annotations

from pathlib import Path


def _find_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "@pipelines").is_dir():
            return parent
    raise FileNotFoundError("Cannot locate project root (no @pipelines directory found upward)")


ROOT = _find_root()

# lint (ruff + mypy) 대상 — relative to ROOT
LINT_TARGETS = [
    "200.DRO/src",
    "200.DRO/mocks",
    "400.CM/src",
    "300.Actor/src",
    "300.Actor/mocks",
    "100.Nexus/src",
    "shared",
    "tests/validate",
    "tests/lint",
    "tests/invoke",
    "tests/probe",
    "tests/enact",
    "tests/play",
    "tests/endpoint",
]

# 보안 SAST (bandit) 대상 — 운영 코드만
SECURITY_TARGETS = [
    "200.DRO/src",
    "400.CM/src",
    "300.Actor/src",
    "100.Nexus/src",
    "shared",
]

# pip-audit 대상 — pyproject.toml 보유 디렉토리
AUDIT_TARGETS = [
    "200.DRO",
    "400.CM",
    "300.Actor",
    "100.Nexus",
    "shared",
    "tests/validate",
    "tests/lint",
    "tests/invoke",
    "tests/probe",
    "tests/enact",
    "tests/play",
    "tests/endpoint",
]

# 공통 제외 디렉토리
EXCLUDES = (".venv", "__pycache__", "alembic", "node_modules", ".git")
