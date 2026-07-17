"""Stage 1 — Pipeline JSON jsonschema Draft 7 strict validate.

`@contracts/_shared/pipeline-definition.schema.json` 으로 raw JSON 을 strict
validate. `additionalProperties: false`, `oneOf`, `required`, `pattern`, enum
모두 자동 검출. 구설계 키 (W{NN}, step.type, sub_pipeline, parallel_task 등)
가 들어오면 schema 가 거부.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import jsonschema

from .._common import ValidationReport

STAGE_NAME = "schema (jsonschema)"


def validate_pipeline_schema(
    pid: str,
    file_path: Path,
    raw: dict[str, Any],
    schema: dict[str, Any],
    rep: ValidationReport,
) -> bool:
    """raw JSON 을 pipeline-definition.schema.json 으로 strict validate.

    반환: True = 통과, False = 실패. 실패 시 모든 위반 사항을 rep.err 로 누적.
    """
    validator = jsonschema.Draft7Validator(schema)
    errs = sorted(validator.iter_errors(raw), key=lambda e: list(e.absolute_path))
    if not errs:
        rep.stage_pass[STAGE_NAME] += 1
        return True
    for err in errs:
        path = ".".join(str(p) for p in err.absolute_path) or "root"
        rep.err(f"[{pid}] stage1 schema {path}: {err.message[:200]}")
    return False
