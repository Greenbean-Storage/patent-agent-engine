"""
dispatch_resolver — dispatch_to.actions + 마지막 step 의 dispatch_choice → 다음 chain(s) 결정.

DRO 전용 모듈 (구 shared/venezia_pipeline_runtime 에서 흡수 — 제품 소비자가
200.DRO/src/orchestrator.py 단독, Actor 재설계 A5·C-3).

max_self_recursion: 코드 default 3. 같은 pipeline_id 가 ancestor_chain_ids 안에
3회 이상 등장 시 강제 종료.
"""

from __future__ import annotations

from typing import Any

DEFAULT_MAX_SELF_RECURSION = 3


class DispatchError(Exception):
    """dispatch resolve 실패."""


def resolve_dispatch(
    *,
    pipeline_id: str,
    dispatch_to: dict[str, Any],
    last_step_output: dict[str, Any] | None,
    ancestor_pipeline_ids: list[str],
    max_self_recursion: int = DEFAULT_MAX_SELF_RECURSION,
) -> list[str]:
    """다음 시작할 pipeline_id 들 반환 (빈 list = exit).

    동작:
    1. actions 가 빈 list 면 [] 반환 (exit).
    2. actions 길이 1 + dispatch_to 에 from 없거나 last_step_output 무관 → actions[0] 그대로.
    3. actions 길이 >1 → last_step_output 의 dispatch_choice 정수로 actions[index] 선택.
    4. 결과의 각 pipeline_id 에 대해 self-recursion 카운트 확인. max 초과 시 해당 self-call 제외.
    """
    actions = dispatch_to.get("actions")
    if actions is None:
        raise DispatchError(f"dispatch_to.actions 없음 ({pipeline_id})")
    if not isinstance(actions, list):
        raise DispatchError(f"dispatch_to.actions 가 list 아님: {type(actions).__name__}")

    if len(actions) == 0:
        return []

    # 단일 다음 (분기 없음)
    if len(actions) == 1:
        choice = actions[0]
    else:
        if not isinstance(last_step_output, dict):
            raise DispatchError(
                f"dispatch_to.actions 가 {len(actions)} 개인데 마지막 step output 없음 "
                f"({pipeline_id})"
            )
        idx = last_step_output.get("dispatch_choice")
        if not isinstance(idx, int):
            raise DispatchError(
                f"last_step_output.dispatch_choice 가 정수 아님 ({pipeline_id}): {idx!r}"
            )
        if not (0 <= idx < len(actions)):
            raise DispatchError(
                f"dispatch_choice={idx} 범위 초과 "
                f"(actions 길이 {len(actions)}, pipeline {pipeline_id})"
            )
        choice = actions[idx]

    if not isinstance(choice, list):
        raise DispatchError(
            f"dispatch_to.actions[*] 가 list 아님: {type(choice).__name__} ({pipeline_id})"
        )

    # self-recursion 가드
    self_count_in_ancestors = ancestor_pipeline_ids.count(pipeline_id)
    result: list[str] = []
    for next_pid in choice:
        if not isinstance(next_pid, str):
            raise DispatchError(f"pipeline_id 가 string 아님: {next_pid!r}")
        if next_pid == pipeline_id and self_count_in_ancestors + 1 > max_self_recursion:
            # 가드: 종료 (해당 self-call 무시)
            continue
        result.append(next_pid)
    return result
