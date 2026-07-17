"""Pipeline JSON 로드 — P{NN} 전용. 구설계 (W{NN}, step.type/next, sub_pipeline 등) fail-loud.

venezia_pipeline_runtime.loader 가 4-layer cascading 합성 + internal shape 반환.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from venezia_pipeline_runtime import load_pipeline_cascaded
from venezia_pipeline_runtime.loader import parse_pipeline_filename

from .config import settings

_pipeline_cache: dict[str, dict[str, Any]] = {}

_P_FILENAME_RE = re.compile(r"^P\d{2}\.R\d{2}\.[A-Z][A-Z0-9_]*\.pipeline\.json$")

# 구설계 잔재 — 발견 시 fail-loud.
_LEGACY_TOP_KEYS = {
    "version",
    "$schema",
    "entry",
    "metadata",
    "error_handling",
    "pipeline_id",
}
_LEGACY_STEP_KEYS = {
    "type",
    "next",
    "system_prompt",
    "input",
    "priority_context_references",
    "available_tools",
    "output_schema",
    "context_manager_reads",
    "mode",
    "over",
    "item_var",
    "task",
    "tasks",
    "bind_results",
    "timeout_per_item",
    "on_error",
    "branches",
    "service",
    "action",
    "calls",
    "response_map",
    "sub_pipeline",
}
# LLM 의 llm_tools 는 자기 chain 안 자원 fetch 만 허용. cross-persona 도구 금지.
# 출처: 300.Actor/src/tools/fetch/__init__.py + @contracts/_shared/pipeline-definition.schema.json
_LLM_TOOL_ALLOWLIST = {
    "fetch_dialog",
    "fetch_step_output",
    "fetch_drawing",
    "list_drawings",
    "fetch_outputs",
    "fetch_conversation",
}


def _assert_no_legacy_instructions(step: dict[str, Any], file_path: Path, where: str) -> None:
    """instructions 가 list/string (구 형식) 이면 RuntimeError. 객체 형태만 허용."""
    inst = step.get("instructions")
    if inst is None:
        return
    if isinstance(inst, list):
        raise RuntimeError(
            f"legacy instructions: list[str] in {file_path} {where} — "
            "{inline: '...'} 또는 {reference: '@pipelines/.../*.md'} 객체로 마이그레이션 필요"
        )
    if isinstance(inst, str):
        raise RuntimeError(
            f"legacy instructions: string in {file_path} {where} — "
            "{inline: '...'} 또는 {reference: '@pipelines/.../*.md'} 객체로 마이그레이션 필요"
        )


def _assert_no_legacy_keys(raw: dict[str, Any], file_path: Path) -> None:
    """파일 raw JSON 에 구설계 키 있으면 RuntimeError."""
    found_top = _LEGACY_TOP_KEYS & set(raw.keys())
    if found_top:
        raise RuntimeError(
            f"legacy top-level keys {sorted(found_top)} in {file_path} — "
            "P{NN} 포맷만 지원. W{NN} 등 구설계는 마이그레이션 필요."
        )
    for idx, step in enumerate(raw.get("steps") or []):
        if isinstance(step, list):
            for sidx, sub in enumerate(step):
                if isinstance(sub, dict):
                    bad = _LEGACY_STEP_KEYS & set(sub.keys())
                    if bad:
                        raise RuntimeError(
                            f"legacy step keys {sorted(bad)} in {file_path} "
                            f"steps[{idx}][{sidx}] — P{{NN}} 포맷만 지원"
                        )
                    _assert_no_legacy_instructions(sub, file_path, f"steps[{idx}][{sidx}]")
            continue
        if not isinstance(step, dict):
            continue
        bad = _LEGACY_STEP_KEYS & set(step.keys())
        if bad:
            raise RuntimeError(
                f"legacy step keys {sorted(bad)} in {file_path} steps[{idx}] — P{{NN}} 포맷만 지원"
            )
        _assert_no_legacy_instructions(step, file_path, f"steps[{idx}]")


def _assert_no_cross_persona_tools(cascaded: dict[str, Any], file_path: Path) -> None:
    """LLM step 의 effective_llm_tools 에 self-chain fetch_* 외 도구 발견 시 RuntimeError."""
    for idx, step in enumerate(cascaded.get("steps") or []):
        if not isinstance(step, dict):
            continue
        tools = step.get("effective_llm_tools") or step.get("llm_tools") or []
        for t in tools:
            name = t if isinstance(t, str) else (t.get("name") if isinstance(t, dict) else None)
            if name and name not in _LLM_TOOL_ALLOWLIST:
                raise RuntimeError(
                    f"cross-persona llm_tool '{name}' in {file_path} steps[{idx}] — "
                    "Actor 끼리 직접 통신 금지. cross-persona 호출은 dispatch_to 로만. "
                    f"허용 도구: {sorted(_LLM_TOOL_ALLOWLIST)}"
                )


def _index() -> dict[str, Path]:
    """pipeline_id → 파일 경로. 파일명 = source of truth (P{NN}.R{NN}.TITLE)."""
    idx: dict[str, Path] = {}
    for f in Path(settings.PIPELINES_DIR).rglob("*.pipeline.json"):
        if not _P_FILENAME_RE.match(f.name):
            raise RuntimeError(
                f"non-P{{NN}} pipeline file detected: {f} — "
                "모든 pipeline 은 P{NN}.R{NN}.TITLE.pipeline.json 포맷이어야 함"
            )
        meta = parse_pipeline_filename(f.name)
        idx[meta["pipeline_id"]] = f
    return idx


_index_cache: dict[str, Path] | None = None


def _convert_single_step(step: dict[str, Any], idx: int, persona_prompt: str) -> dict[str, Any]:
    merged = dict(step)
    merged.setdefault("id", str(idx))
    if merged.get("instructions"):
        merged["system_prompt"] = persona_prompt  # composer 가 사용
    return merged


def _coerce_to_orchestrator(cascaded: dict[str, Any]) -> dict[str, Any]:
    """venezia_pipeline_runtime.loader 의 internal shape → orchestrator 가 읽는 키.

    step list 안에 list 가 nested = 정적 병렬 group. dict 는 단일 step.
    """
    persona_prompt = cascaded.get("persona_prompt") or ""
    pipeline_id = cascaded["pipeline_id"]
    new_steps: list[Any] = []
    for idx, step in enumerate(cascaded.get("steps") or []):
        if isinstance(step, list):
            new_steps.append(
                [
                    _convert_single_step(sub, idx, persona_prompt)
                    for sub in step
                    if isinstance(sub, dict)
                ]
            )
        elif isinstance(step, dict):
            new_steps.append(_convert_single_step(step, idx, persona_prompt))
    return {
        "pipeline_id": pipeline_id,
        "persona": cascaded.get("persona"),
        "description": cascaded.get("description") or "",
        "steps": new_steps,
        "dispatch_to": cascaded.get("dispatch_to"),
        "_runtime_cascaded": cascaded,
    }


def load_pipeline(pipeline_id: str) -> dict[str, Any]:
    if pipeline_id in _pipeline_cache:
        return _pipeline_cache[pipeline_id]
    global _index_cache
    if _index_cache is None:
        _index_cache = _index()
    f = _index_cache.get(pipeline_id)
    if f is None:
        raise FileNotFoundError(
            f"pipeline_id '{pipeline_id}' not found in {settings.PIPELINES_DIR}"
        )
    raw = json.loads(f.read_text(encoding="utf-8"))
    _assert_no_legacy_keys(raw, f)
    cascaded = load_pipeline_cascaded(pipeline_id, root=Path(settings.PIPELINES_DIR))
    _assert_no_cross_persona_tools(cascaded, f)
    data = _coerce_to_orchestrator(cascaded)
    _pipeline_cache[pipeline_id] = data
    return data


class AmbiguousPipelineId(ValueError):
    def __init__(self, prefix: str, candidates: list[str]) -> None:
        super().__init__(
            f"pipeline_id prefix '{prefix}' is ambiguous — {len(candidates)} matches: {candidates}"
        )
        self.prefix = prefix
        self.candidates = candidates


def resolve_pipeline_id(prefix: str) -> str:
    """`P03.R00` 같은 prefix → `P03.R00.PRIOR_ART_SEARCH_ANALYZE` full ID.

    - exact match 면 그대로 반환
    - prefix 만 매칭되면 유일 매칭 시 반환, 2개+ AmbiguousPipelineId, 0개 KeyError
    """
    global _index_cache
    if _index_cache is None:
        _index_cache = _index()
    if prefix in _index_cache:
        return prefix
    matches = sorted(pid for pid in _index_cache if pid.startswith(prefix + "."))
    if len(matches) == 0:
        raise KeyError(prefix)
    if len(matches) == 1:
        return matches[0]
    raise AmbiguousPipelineId(prefix, matches)


def list_pipelines() -> list[dict[str, Any]]:
    """전체 pipeline 인벤토리 — `[{pipeline_id, persona, description}, ...]` (id 오름차순)."""
    global _index_cache
    if _index_cache is None:
        _index_cache = _index()
    out: list[dict[str, Any]] = []
    for pid in sorted(_index_cache.keys()):
        try:
            data = load_pipeline(pid)
        except Exception as e:  # noqa: BLE001
            out.append({"pipeline_id": pid, "persona": None, "description": "", "error": str(e)})
            continue
        out.append(
            {
                "pipeline_id": pid,
                "persona": data.get("persona"),
                "description": data.get("description") or "",
            }
        )
    return out
