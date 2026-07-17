"""Stage 2 — Shared loader 4-layer cascading + effective_llm_tools 검사.

`shared/venezia_pipeline_runtime/loader.py` 의 `load_pipeline_cascaded` 사용.
cascading 후의 effective_llm_tools 가 self-chain fetch_* allowlist 안에 있는지 확인.
raw step.llm_tools 만 보면 놓치는 머지 결과를 잡음.
"""

from __future__ import annotations

from typing import Any

from venezia_pipeline_runtime.loader import load_pipeline_cascaded

from .._common import PIPELINES_DIR, ValidationReport

STAGE_NAME = "cascading (shared loader)"


def validate_cascading(
    pid: str,
    rep: ValidationReport,
    allowlist: set[str],
) -> dict[str, Any] | None:
    """shared loader 로 4-layer cascading 후 effective_llm_tools 검사.

    반환: cascaded dict (이후 단계에서 활용), 또는 None (cascading 자체 실패).
    """
    try:
        cascaded = load_pipeline_cascaded(pid, root=PIPELINES_DIR)
    except Exception as e:
        rep.err(f"[{pid}] stage2 cascading 실패: {e}")
        return None

    ok = True
    for idx, step in enumerate(cascaded.get("steps") or []):
        # nested list (정적 병렬 group) 도 동일하게 검사
        if isinstance(step, list):
            for sidx, sub in enumerate(step):
                if isinstance(sub, dict):
                    if not _check_effective_llm_tools(pid, f"{idx}[{sidx}]", sub, allowlist, rep):
                        ok = False
            continue
        if not isinstance(step, dict):
            continue
        if not _check_effective_llm_tools(pid, str(idx), step, allowlist, rep):
            ok = False

    if ok:
        rep.stage_pass[STAGE_NAME] += 1
    return cascaded


def _check_effective_llm_tools(
    pid: str,
    step_label: str,
    step: dict[str, Any],
    allowlist: set[str],
    rep: ValidationReport,
) -> bool:
    """cascading 후 step.effective_llm_tools 또는 step.llm_tools 가 allowlist 안인지."""
    tools = step.get("effective_llm_tools") or step.get("llm_tools") or []
    ok = True
    for t in tools:
        name = t if isinstance(t, str) else (t.get("name") if isinstance(t, dict) else None)
        if name and name not in allowlist:
            rep.err(
                f"[{pid}] stage2 step[{step_label}] effective_llm_tools '{name}' — "
                f"cross-persona 도구 금지. allowlist: {sorted(allowlist)}"
            )
            ok = False
    return ok
