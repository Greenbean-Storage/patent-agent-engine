"""Stage 14 — capstone: 구조적 파일 검증 커버리지 census + pyproject 정합 + data 파싱.

"전부 validate 한지" 보장 stage. repo 의 모든 구조적 파일(*.json/*.yaml/*.yml/*.toml)이
(a) 어떤 stage 가 검증하거나 (b) 명시 data/도메인 allowlist 중 하나로 분류되는지 확인 —
미분류 파일 = fail. 미래 신규 구조적 파일도 자동 포착(allowlist 추가 강제).

추가로:
- pyproject.toml requires-python 정합 (엔진+tests 패키지; tools/* 는 별도 도메인 제외)
- tests/data/**/*.json 파싱 가능 (fixture/sample 무결성)
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from .._common import ROOT, ValidationReport

STAGE_NAME = "coverage census"

_EXCLUDE_DIRS = {
    ".venv",
    "__pycache__",
    "node_modules",
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "dist",
    "build",
}
_EXTS = ("*.json", "*.yaml", "*.yml", "*.toml")


def _iter_structured() -> list[Path]:
    out: list[Path] = []
    for ext in _EXTS:
        for p in ROOT.rglob(ext):
            parts = p.relative_to(ROOT).parts
            if any(part in _EXCLUDE_DIRS or part.endswith(".egg-info") for part in parts):
                continue
            out.append(p)
    return sorted(set(out))


def _classify(rel: str) -> str | None:
    """rel(posix) → 검증 owner 라벨. None = 미분류(uncovered)."""
    # --- stage 가 검증하는 파일 ---
    if rel.startswith("@pipelines/"):
        return "Stage 1-6 / cascading / reference"
    if rel.startswith("@contracts/"):
        return "Stage 7 (contracts meta-schema)"
    if rel == ".docs/Architectures/external_api/openapi.nexus.json":
        return "Stage 9 (openapi)"
    if rel == ".docs/Architectures/external_api/asyncapi.yaml":
        return "Stage 13 (asyncapi)"
    if rel in (
        "shared/venezia_memory/scaffolding.yaml",
        "@deployment/topology.yaml",
        "@deployment/knobs.yaml",
        "@deployment/engine.config.yaml",
        "@deployment/engine-config.schema.json",
        "@deployment/media.config.yaml",
        "@deployment/media-config.schema.json",
        "compose.yaml",
        "compose.override.yaml",
    ):
        return "Stage 12 (infra config)"
    if rel.endswith("pyproject.toml"):
        return "Stage 14 (pyproject)"
    # --- data / 별도 도메인 / config allowlist (사유 기재) ---
    if rel.startswith("@knowledge/"):
        return "data: knowledge 도메인 (make verify-classification/drafting/rejections)"
    if rel.startswith("tests/data/"):
        return "data: fixture/sample"
    if rel.startswith("tools/"):
        return "data: build 도구 (자체 도메인)"
    if rel.startswith("tests/validate/validate/_schemas/"):
        return "data: vendored 메타스키마 (asyncapi 등)"
    if rel.endswith("pyrightconfig.json"):
        return "config: pyright (IDE)"
    if rel.startswith(".claude/"):
        return "config: harness"
    if rel.startswith(".serena/"):
        return "config: serena (MCP tool 로컬 설정 — .claude 와 동류, gitignored)"
    if rel == "@deployment/profile.stack.yaml":
        return "generated: deployment profile (gitignored — make deploy 가 씀, fresh clone 엔 부재)"
    return None


_PYPROJECT_CONSISTENCY_EXCLUDE = ("tools/",)  # 별도 도메인 — 독립 python floor 허용


def _check_pyproject_consistency(rep: ValidationReport) -> bool:
    ok = True
    floors: dict[str, str] = {}
    for p in ROOT.rglob("pyproject.toml"):
        rel = p.relative_to(ROOT).as_posix()
        if any(part in _EXCLUDE_DIRS for part in p.relative_to(ROOT).parts):
            continue
        if rel.startswith(_PYPROJECT_CONSISTENCY_EXCLUDE):
            continue
        try:
            data = tomllib.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            rep.err(f"[census] {rel} TOML 파싱 실패: {e}")
            ok = False
            continue
        rp = (data.get("project") or {}).get("requires-python")
        if rp:
            floors[rel] = rp
    distinct = set(floors.values())
    if len(distinct) > 1:
        rep.err(f"[census] pyproject requires-python 불일치 (엔진+tests): {floors}")
        ok = False
    return ok


def _check_data_parseable(rep: ValidationReport) -> bool:
    ok = True
    data_dir = ROOT / "tests" / "data"
    if data_dir.is_dir():
        for p in sorted(data_dir.rglob("*.json")):
            try:
                json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:
                rep.err(f"[census] fixture/sample JSON 파싱 실패 {p.relative_to(ROOT)}: {e}")
                ok = False
    return ok


def validate_census(rep: ValidationReport) -> bool:
    ok = True

    # A) 커버리지 census — 모든 구조적 파일이 분류되는지
    uncovered: list[str] = []
    for p in _iter_structured():
        rel = p.relative_to(ROOT).as_posix()
        if _classify(rel) is None:
            uncovered.append(rel)
    if uncovered:
        rep.err(
            f"[census] 검증 미커버 구조적 파일 {len(uncovered)}개 — stage 또는 allowlist 추가 필요: "
            + ", ".join(uncovered[:12])
            + (" …" if len(uncovered) > 12 else "")
        )
        ok = False

    # B) pyproject 정합
    if not _check_pyproject_consistency(rep):
        ok = False

    # C) fixture/sample 파싱 무결성
    if not _check_data_parseable(rep):
        ok = False

    if ok:
        rep.stage_pass[STAGE_NAME] += 1
    return ok
