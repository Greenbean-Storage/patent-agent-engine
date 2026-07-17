"""validate 공통 헬퍼 — ROOT 탐지, ValidationReport, schema/contract 로더."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _find_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "@pipelines").is_dir():
            return parent
    raise FileNotFoundError("Cannot locate project root (no @pipelines directory found upward)")


ROOT = _find_root()
PIPELINES_DIR = ROOT / "@pipelines"
CONTRACTS_DIR = ROOT / "@contracts"
PIPELINE_SCHEMA_PATH = CONTRACTS_DIR / "_shared" / "pipeline-definition.schema.json"

# shared/venezia_pipeline_runtime 를 import path 에 추가
if str(ROOT / "shared") not in sys.path:
    sys.path.insert(0, str(ROOT / "shared"))


STAGE_NAMES = (
    "schema (jsonschema)",
    "cascading (shared loader)",
    "cross-reference",
    "tool registry",
    "no inputs placeholder",
    "cm:// pointer notation",
    "contracts (meta-schema)",
    "contracts extended (IOM)",
    "external_api spec",
    "ws consistency",
    "dead schema",
    "infra config",
    "asyncapi spec",
    "coverage census",
    "parallel shape",
)


class ValidationReport:
    """모든 stage 가 공유하는 에러/통과 누적기."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.checked: int = 0
        self.stage_pass: dict[str, int] = {name: 0 for name in STAGE_NAMES}

    def err(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    @property
    def ok(self) -> bool:
        return not self.errors


def load_pipeline_schema() -> dict[str, Any]:
    if not PIPELINE_SCHEMA_PATH.exists():
        raise FileNotFoundError(f"pipeline-definition.schema.json 없음: {PIPELINE_SCHEMA_PATH}")
    return json.loads(PIPELINE_SCHEMA_PATH.read_text(encoding="utf-8"))


def llm_tool_allowlist(schema: dict[str, Any]) -> set[str]:
    """Step.properties.llm_tools.items.enum → set. schema = single source of truth."""
    try:
        return set(schema["$defs"]["Step"]["properties"]["llm_tools"]["items"]["enum"])
    except (KeyError, TypeError) as e:
        raise RuntimeError(f"schema 에서 llm_tools allowlist 추출 실패: {e}") from e


def load_persona_common(persona: int) -> dict[str, Any] | None:
    prefix = f"{persona:02d}."
    for child in PIPELINES_DIR.iterdir():
        if child.is_dir() and child.name.startswith(prefix):
            f = child / f"P{persona:02d}.COMMON.json"
            if not f.exists():
                return None
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                return None
    return None


def load_contract_schema(persona: int, contract_id: str) -> dict[str, Any] | None:
    """@contracts/<persona>/stages/<contract_id>.schema.json 로드."""
    prefix = f"{persona:02d}."
    if not CONTRACTS_DIR.exists():
        return None
    for child in CONTRACTS_DIR.iterdir():
        if child.is_dir() and child.name.startswith(prefix):
            f = child / "stages" / f"{contract_id}.schema.json"
            if f.exists():
                try:
                    return json.loads(f.read_text(encoding="utf-8"))
                except Exception:
                    return None
    return None


def load_global() -> dict[str, Any]:
    """@pipelines/_shared/GLOBAL.json 로드. 실패 시 빈 dict + 호출자가 err 처리."""
    f = PIPELINES_DIR / "_shared" / "GLOBAL.json"
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {}
