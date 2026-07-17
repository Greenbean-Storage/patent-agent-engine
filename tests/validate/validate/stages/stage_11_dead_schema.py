"""Stage 11 — dead contract schema 탐지 (WARN).

`@contracts/<persona>/stages/*.schema.json` 중 어떤 pipeline 의 `output_contract` 도
참조하지 않는 schema 를 보고. 일부는 미구현 pipeline(P02.R99 등) 용 예약일 수 있어
삭제 강제는 아님 → **WARN** (validate PASS 막지 않음). 메타검증은 Stage 7 이 이미 수행.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from .._common import CONTRACTS_DIR, PIPELINES_DIR, ValidationReport

STAGE_NAME = "dead schema"


def _walk(obj: Any) -> Iterator[Any]:
    yield obj
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _referenced_contracts() -> set[str]:
    refs: set[str] = set()
    for f in PIPELINES_DIR.glob("**/*.pipeline.json"):
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for node in _walk(raw):
            if isinstance(node, dict) and isinstance(node.get("output_contract"), str):
                refs.add(node["output_contract"])
    return refs


def validate_dead_schema(rep: ValidationReport) -> bool:
    """persona stage schema 중 미참조분을 WARN 으로 보고 (stage 는 항상 통과)."""
    referenced = _referenced_contracts()
    dead: list[str] = []
    for schema_file in sorted(CONTRACTS_DIR.glob("*/stages/*.schema.json")):
        contract_id = schema_file.name.removesuffix(".schema.json")
        if contract_id not in referenced:
            dead.append(str(schema_file.relative_to(CONTRACTS_DIR)))
    if dead:
        rep.warn(
            f"[dead-schema] pipeline output_contract 미참조 {len(dead)}개 "
            f"(미구현 pipeline 예약 가능): {', '.join(dead[:8])}" + (" …" if len(dead) > 8 else "")
        )
    rep.stage_pass[STAGE_NAME] += 1
    return True
