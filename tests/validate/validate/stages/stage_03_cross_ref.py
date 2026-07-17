"""Stage 3 — Cross-reference (pipeline ↔ contract / pipeline ↔ pipeline).

step.output_contract → @contracts/<persona>/stages/<id>.schema.json 파일 존재.
4-layer name+source 중복 conflict (GLOBAL/persona.COMMON/pipeline.common).
dispatch_to.actions 길이 ↔ 마지막 step 의 dispatch_choice integer maximum.
dispatch_to.actions[*][*] 의 pipeline_id 가 @pipelines/ 안에 실재.
"""

from __future__ import annotations

import json
from typing import Any

from .._common import ROOT, ValidationReport, load_contract_schema

STAGE_NAME = "cross-reference"


def validate_cross_reference(
    pid: str,
    persona: int,
    raw: dict[str, Any],
    global_data: dict[str, Any],
    persona_common: dict[str, Any] | None,
    all_pipeline_ids: set[str],
    rep: ValidationReport,
) -> bool:
    """contract schema 파일 존재 + 4-layer name+source 중복 + dispatch_choice 일관성
    + dispatch_to.actions 의 pipeline_id 가 실재.
    """
    ok = True

    # 4-layer name+source conflict (GLOBAL/persona.COMMON/pipeline.common)
    common = raw.get("common") or {}
    for layer_key in ("inject_context", "recommended_context", "fragments"):
        merged: dict[str, list[tuple[str, Any]]] = {}
        for layer_name, layer_data in [
            ("GLOBAL", global_data),
            ("persona", persona_common or {}),
            ("pipeline", common),
        ]:
            items = (layer_data or {}).get(layer_key) or {}
            if not isinstance(items, dict):
                continue
            for name, source in items.items():
                merged.setdefault(name, []).append((layer_name, source))
        for name, sources_list in merged.items():
            if len(sources_list) > 1:
                source_values = [s[1] for s in sources_list]
                if len(set(json.dumps(s, sort_keys=True) for s in source_values)) == 1:
                    rep.err(
                        f"[{pid}] stage3 {layer_key}.'{name}' — same source 중복 in "
                        f"{[s[0] for s in sources_list]}"
                    )
                    ok = False

    # dispatch_to.actions 의 pipeline_id 가 @pipelines/ 안에 실재
    steps = raw.get("steps") or []
    dispatch_to = raw.get("dispatch_to") or {}
    actions = dispatch_to.get("actions") if isinstance(dispatch_to, dict) else None
    if isinstance(actions, list):
        for ai, action_list in enumerate(actions):
            if not isinstance(action_list, list):
                continue
            for ti, target_pid in enumerate(action_list):
                if not isinstance(target_pid, str):
                    continue
                if target_pid not in all_pipeline_ids:
                    rep.err(
                        f"[{pid}] stage3 dispatch_to.actions[{ai}][{ti}] = "
                        f"'{target_pid}' — @pipelines/ 에 해당 P{{NN}} 파일 없음"
                    )
                    ok = False

    # dispatch_to.actions 길이 ↔ 마지막 step 의 dispatch_choice 강제 (A-6 — 발생 불가화).
    # dispatch_choice 를 output_contract 의 required + 범위제약 정수([0, len-1])로 못박아
    # LLM 의 native structured-output(+jsonschema 검증 retry)이 그 범위 밖을 내지 못하게 →
    # resolve_dispatch 의 "정수 아님/범위 초과/누락" DispatchError 를 정적으로 불가능화.
    if isinstance(actions, list) and len(actions) > 1 and steps:
        # 마지막 dict step (nested list 끝이면 그 안의 마지막 dict)
        last_step = None
        if isinstance(steps[-1], dict):
            last_step = steps[-1]
        elif isinstance(steps[-1], list) and steps[-1]:
            tail = steps[-1][-1]
            if isinstance(tail, dict):
                last_step = tail
        contract_id = last_step.get("output_contract") if last_step else None
        if not contract_id:
            rep.err(
                f"[{pid}] stage3 multi-action dispatch_to({len(actions)}) 인데 마지막 step 에 "
                f"output_contract 없음 — dispatch_choice SoT 강제 불가 (A-6)"
            )
            ok = False
        else:
            schema_data = load_contract_schema(persona, contract_id)
            if schema_data:
                props = (schema_data.get("properties") or {}).get("dispatch_choice")
                required = schema_data.get("required") or []
                if not isinstance(props, dict):
                    rep.err(
                        f"[{pid}] stage3 multi-action dispatch_to 인데 "
                        f"{contract_id} schema 에 dispatch_choice 필드 없음"
                    )
                    ok = False
                else:
                    if props.get("type") != "integer":
                        rep.err(
                            f"[{pid}] stage3 {contract_id}.dispatch_choice type 은 integer "
                            f"여야 (A-6 SoT 강제): {props.get('type')!r}"
                        )
                        ok = False
                    if props.get("minimum") != 0:
                        rep.err(
                            f"[{pid}] stage3 {contract_id}.dispatch_choice.minimum 은 0 "
                            f"이어야 (A-6): {props.get('minimum')!r}"
                        )
                        ok = False
                    max_val = props.get("maximum")
                    if not (isinstance(max_val, int) and max_val + 1 == len(actions)):
                        rep.err(
                            f"[{pid}] stage3 dispatch_to.actions 길이 {len(actions)} "
                            f"↔ {contract_id}.dispatch_choice.maximum {max_val} 불일치 "
                            f"(maximum=len-1 이어야)"
                        )
                        ok = False
                    if "dispatch_choice" not in required:
                        rep.err(
                            f"[{pid}] stage3 {contract_id}.dispatch_choice 가 required 아님 — "
                            f"LLM 출력 누락 가능 (A-6 강제: required 필수)"
                        )
                        ok = False

    # progress 문구 강제 (#6) — 파이프라인이 display_status 를 쓰면(opt-in) 전 RT step 에 필수.
    # (빈 fallback 구조적 제거.) 미선언 파이프라인(미구현)은 미강제 — 활성화 시 opt-in 하면 전수 강제.
    def _has_ds(s: Any) -> bool:
        ds = s.get("display_status") if isinstance(s, dict) else None
        return isinstance(ds, dict) and isinstance(ds.get("ko"), str) and bool(ds["ko"].strip())

    pipeline_uses_progress = any(
        (any(_has_ds(sub) for sub in step) if isinstance(step, list) else _has_ds(step))
        for step in steps
    )

    # step.output_contract → contract schema 파일 존재 + instructions.reference .md 파일 존재
    # + RT step progress 문구(display_status.ko) 강제(opt-in 파이프라인)
    def _check_step(step: dict[str, Any], where: str) -> None:
        nonlocal ok
        cid = step.get("output_contract")
        if cid and not load_contract_schema(persona, cid):
            rep.err(f"[{pid}] stage3 {where} output_contract '{cid}' schema 파일 없음")
            ok = False
        instr = step.get("instructions")
        if isinstance(instr, dict):
            ref = instr.get("reference")
            if isinstance(ref, str) and ref and not (ROOT / ref).is_file():
                rep.err(
                    f"[{pid}] stage3 {where} instructions.reference '{ref}' 파일 없음 ({ROOT / ref})"
                )
                ok = False
        if (
            pipeline_uses_progress
            and (step.get("instructions") or step.get("tool"))
            and not _has_ds(step)
        ):
            rep.err(
                f"[{pid}] stage3 {where} — RT step 에 display_status.ko 누락 "
                f"(progress 문구 강제 #6: progress 쓰는 파이프라인은 전 RT step 필수)"
            )
            ok = False

    for idx, step in enumerate(steps):
        if isinstance(step, list):
            for sidx, sub in enumerate(step):
                if isinstance(sub, dict):
                    _check_step(sub, f"step[{idx}][{sidx}]")
            continue
        if isinstance(step, dict):
            _check_step(step, f"step[{idx}]")

    if ok:
        rep.stage_pass[STAGE_NAME] += 1
    return ok
