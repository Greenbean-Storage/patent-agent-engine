"""Stage 8 — Contracts extended: IOM schema + sample IOM 인스턴스 검증 (hard-fail).

`@contracts/_shared/invention-object-model.schema.json` 로 ① 인라인 최소 sample +
② 실 seed 샘플(`tests/data/iom-samples/*.json` — seed/play/probe 가 IOM 으로 PUT) 을 validate.
구 warn-only(soft) 폐지 — schema 누락도, sample 위반도 **hard-fail**. (사용자: 툴에 한계 두지 않기.)
sample 은 schema 와 항상 일치하게 유지 — schema 진화 시 sample 도 같이 갱신.
"""

from __future__ import annotations

import json

import jsonschema

from .._common import CONTRACTS_DIR, ValidationReport

STAGE_NAME = "contracts extended (IOM)"

# top-level required = [meta, bibliographic, claims]. 최소 유효 인스턴스 (optional 필드 생략).
_SAMPLE_IOM = {
    "meta": {
        "model_id": "00000000-0000-0000-0000-000000000000",
        "version": "1.0.0",
        "user_id": "u-sample",
        "work_id": "i-sample",
    },
    "bibliographic": {"title": {"ko": "테스트 발명"}},
    "claims": [{"number": 1, "type": "independent", "text": "테스트 독립항 본문."}],
}


def validate_contracts_extended(rep: ValidationReport) -> bool:
    """IOM schema 존재 + sample IOM 이 schema 로 valid (hard-fail)."""
    p = CONTRACTS_DIR / "_shared" / "invention-object-model.schema.json"
    if not p.exists():
        rep.err(f"[contracts.iom] IOM schema 없음 (필수 SoT): {p}")
        return False
    try:
        iom_schema = json.loads(p.read_text(encoding="utf-8"))
        jsonschema.validate(_SAMPLE_IOM, iom_schema)
    except jsonschema.ValidationError as e:
        rep.err(f"[contracts.iom] 인라인 sample IOM 이 schema 위반: {e.message[:200]}")
        return False
    except Exception as e:
        rep.err(f"[contracts.iom] schema 로드/검증 실패: {e}")
        return False
    # 실 seed 샘플(seed/play/probe 가 PUT 하는 IOM)도 schema 로 검증 — 드리프트 hard-fail.
    ok = True
    sample_dir = CONTRACTS_DIR.parent / "tests" / "data" / "iom-samples"
    for sp in sorted(sample_dir.glob("*.json")):
        try:
            jsonschema.validate(json.loads(sp.read_text(encoding="utf-8")), iom_schema)
        except jsonschema.ValidationError as e:
            where = "/".join(str(x) for x in e.path) or "(root)"
            rep.err(f"[contracts.iom] seed 샘플 {sp.name} schema 위반 @{where}: {e.message[:150]}")
            ok = False
        except Exception as e:
            rep.err(f"[contracts.iom] seed 샘플 {sp.name} 로드 실패: {e}")
            ok = False
    if not ok:
        return False
    rep.stage_pass[STAGE_NAME] += 1
    return True
