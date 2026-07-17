"""Stage 15 — 정적 병렬 묶음(nested list) 형태 검증 (D-6).

`steps` 안의 list 원소 = 정적 병렬 묶음 (한 자리에서 N RT `asyncio.gather` 동시 실행).
schema(stage 1)가 oneOf [Step | array[Step]] 로 1차 보장하나, **cross-item 제약**(묶음 내 id
유일·명시 id 필수)과 instr XOR tool 은 schema 로 표현 불가 → 본 stage 가 정적 강제:

  - 묶음 비어있지 않음 (빈 list 금지)
  - 각 sub 가 dict (schema 1차 보장 — 방어적 재확인)
  - 각 sub 가 instructions XOR tool (런타임 orchestrator `_run_one_step` 강제를 정적 선행)
  - 각 sub 가 **명시 id 보유** — 병렬 묶음 sub 는 같은 위치 인덱스를 공유하므로 walker
    `_convert_single_step` 의 `setdefault("id", str(idx))` 가 충돌(동일 id) 부여 → 명시 id 필수
  - 같은 묶음 내 id 유일
  - 깊이 1 (list 안 list 금지 — schema 1차 보장, 방어적)
"""

from __future__ import annotations

from typing import Any

from .._common import ValidationReport

STAGE_NAME = "parallel shape"


def _is_rt_step(sub: dict[str, Any]) -> bool:
    """instructions XOR tool — LLM step XOR tool step (orchestrator 런타임 계약과 동형)."""
    return bool(sub.get("instructions")) != bool(sub.get("tool"))


def validate_parallel_shape(pid: str, raw: dict[str, Any], rep: ValidationReport) -> bool:
    """raw pipeline 의 steps 중 정적 병렬 묶음(list 원소) 형태 검증."""
    ok = True
    for idx, step in enumerate(raw.get("steps") or []):
        if not isinstance(step, list):
            continue
        where = f"steps[{idx}]"
        if not step:
            rep.err(f"[{pid}] stage15 {where} — 빈 정적 병렬 묶음 (sub 0개)")
            ok = False
            continue
        seen_ids: dict[str, int] = {}
        for sidx, sub in enumerate(step):
            sw = f"{where}[{sidx}]"
            if isinstance(sub, list):
                rep.err(f"[{pid}] stage15 {sw} — 병렬 묶음 중첩 금지 (깊이 1만 허용)")
                ok = False
                continue
            if not isinstance(sub, dict):
                rep.err(f"[{pid}] stage15 {sw} — 병렬 묶음 원소는 dict step ({type(sub).__name__})")
                ok = False
                continue
            if not _is_rt_step(sub):
                rep.err(
                    f"[{pid}] stage15 {sw} — 병렬 묶음 step 은 instructions XOR tool 정확히 1개"
                )
                ok = False
            sub_id = sub.get("id")
            if not isinstance(sub_id, str) or not sub_id.strip():
                rep.err(
                    f"[{pid}] stage15 {sw} — 병렬 묶음 sub 는 명시 id 필수 "
                    "(위치 인덱스 공유 → walker id 충돌 방지)"
                )
                ok = False
                continue
            if sub_id in seen_ids:
                rep.err(
                    f"[{pid}] stage15 {sw} — 묶음 내 중복 id '{sub_id}' (앞선 [{seen_ids[sub_id]}])"
                )
                ok = False
            seen_ids[sub_id] = sidx
    if ok:
        rep.stage_pass[STAGE_NAME] += 1
    return ok
