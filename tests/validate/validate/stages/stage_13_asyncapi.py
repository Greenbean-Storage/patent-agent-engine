"""Stage 13 — asyncapi.yaml 풀 메타검증 (공식 AsyncAPI 3.0.0 schema, vendored).

`_schemas/asyncapi-3.0.0.json` 는 공식 spec-json-schemas 의 bundled(without-$id, draft-07)
스냅샷 — 런타임 오프라인. WS 표면 spec 의 전 구조를 메타검증 (부분 아님).
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import yaml

from .._common import ROOT, ValidationReport

STAGE_NAME = "asyncapi spec"

_SCHEMA = Path(__file__).resolve().parent.parent / "_schemas" / "asyncapi-3.0.0.json"
_ASYNCAPI = ROOT / ".docs" / "Architectures" / "external_api" / "asyncapi.yaml"


def validate_asyncapi(rep: ValidationReport) -> bool:
    if not _SCHEMA.exists():
        rep.err(f"[asyncapi] vendored 메타스키마 없음: {_SCHEMA}")
        return False
    if not _ASYNCAPI.exists():
        rep.err(f"[asyncapi] asyncapi.yaml 없음: {_ASYNCAPI}")
        return False
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    doc = yaml.safe_load(_ASYNCAPI.read_text(encoding="utf-8"))
    cls = jsonschema.validators.validator_for(schema)
    errs = sorted(cls(schema).iter_errors(doc), key=lambda e: list(e.path))
    if errs:
        for e in errs[:5]:
            rep.err(f"[asyncapi] {list(e.path)}: {e.message[:140]}")
        return False
    rep.stage_pass[STAGE_NAME] += 1
    return True
