"""Stage 7 — Contracts meta-schema 검증 (전수 glob, discover-don't-hardcode).

`@contracts/**/*.json` 의 **모든** schema 가 Draft 7 meta-schema 자체로 valid 한지 확인.
구 하드코딩 13개 목록 폐기 → glob 으로 전수. `00.dro/websocket-events.json` 포함 자동 커버.
`_REQUIRED` 는 "필수 존재 floor" 로만 유지 — SoT schema 가 사라지면 fail (전수 glob 와 별개).
"""

from __future__ import annotations

import json

import jsonschema

from .._common import CONTRACTS_DIR, ValidationReport

STAGE_NAME = "contracts (meta-schema)"

# 필수 존재 floor — 이 SoT schema 가 사라지면 fail (전수 glob 가 "있는 것" 만 검증하므로 보완).
_REQUIRED: tuple[str, ...] = (
    "_shared/reasoning_task.schema.json",
    "_shared/chain_manifest.schema.json",
    "_shared/pipeline-definition.schema.json",
    "_shared/manifest.context.schema.json",
    "_shared/manifest.runtime.schema.json",
    "_shared/manifest.models.schema.json",
    "_shared/manifest.outputs.schema.json",
    "_shared/drawing-manifest.schema.json",
    "_shared/invention-object-model.schema.json",
    "_shared/models/concept-maturity-model.schema.json",
    "_shared/models/concept-discovery-stack.schema.json",
    "_shared/models/user-roadmap.schema.json",
    "00.dro/websocket-events.json",
)


def validate_contracts(rep: ValidationReport) -> bool:
    """@contracts/**/*.json 전수 — 각 파일 Draft 7 meta-schema valid + 필수 floor 존재."""
    ok = True
    if not CONTRACTS_DIR.is_dir():
        rep.err(f"[contracts] @contracts 디렉토리 없음: {CONTRACTS_DIR}")
        return False

    # 1) 필수 floor 존재 확인
    for rel in _REQUIRED:
        if not (CONTRACTS_DIR / rel).exists():
            rep.err(f"[contracts] 필수 schema 없음: @contracts/{rel}")
            ok = False

    # 2) 전수 meta-validate (glob — 하드코딩 아님)
    files = sorted(CONTRACTS_DIR.glob("**/*.json"))
    if not files:
        rep.err("[contracts] @contracts 아래 *.json 0개 — 비정상")
        return False
    for p in files:
        relp = p.relative_to(CONTRACTS_DIR)
        try:
            schema = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            rep.err(f"[contracts] {relp} JSON 파싱 실패: {e}")
            ok = False
            continue
        try:
            jsonschema.Draft7Validator.check_schema(schema)
        except Exception as e:
            rep.err(f"[contracts] {relp} meta-schema invalid: {e}")
            ok = False
    if ok:
        rep.stage_pass[STAGE_NAME] += 1
    return ok
