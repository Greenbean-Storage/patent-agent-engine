"""
loader — 새 P{NN}.R{NN} pipeline 포맷 로드 + 4-layer cascading 합성.

import 자: 200.DRO/src/pipeline_walker.py + tests/validate/validate/cli.py.

4-layer:
- (1) GLOBAL: @pipelines/_shared/GLOBAL.json
- (2) persona: @pipelines/{NN}.{persona}/P{NN}.COMMON.json
- (3) pipeline: 파이프라인 자체의 top.common
- (4) step: step 안 직접 inject_context / recommended_context / fragments

합집합 (memory cache 처럼) — override 없음. 같은 이름 + 같은 source = conflict
(validator 에서 error).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

PIPELINES_ROOT_ENV = "PIPELINES_ROOT"
DEFAULT_PIPELINES_ROOT = Path("/app/@pipelines")


class LoaderError(Exception):
    """파이프라인 로드/cascading 실패."""


_FILENAME_RE = re.compile(
    r"^P(?P<persona>\d{2})\.R(?P<role>\d{2})\.(?P<title>[A-Z][A-Z0-9_]*)\.pipeline\.json$"
)


def parse_pipeline_filename(filename: str) -> dict[str, Any]:
    """P{NN}.R{NN}.{UPPER_SNAKE}.pipeline.json → {pipeline_id, persona, role, title}."""
    m = _FILENAME_RE.match(filename)
    if not m:
        raise LoaderError(
            f"파일명 규칙 위반: {filename} (P{{NN}}.R{{NN}}.{{UPPER_SNAKE}}.pipeline.json)"
        )
    persona = int(m.group("persona"))
    role = int(m.group("role"))
    title = m.group("title")
    pipeline_id = f"P{persona:02d}.R{role:02d}.{title}"
    return {
        "pipeline_id": pipeline_id,
        "persona": persona,
        "role": role,
        "title": title,
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise LoaderError(f"파일 없음: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise LoaderError(f"JSON 파싱 실패 ({path}): {e}") from e


def _find_persona_dir(root: Path, persona: int) -> Path:
    """@pipelines/{NN}.{name}/ 디렉토리 찾기. persona 번호로 매칭."""
    prefix = f"{persona:02d}."
    for child in root.iterdir():
        if child.is_dir() and child.name.startswith(prefix):
            return child
    raise LoaderError(f"persona {persona:02d} 디렉토리 없음 (@pipelines/{persona:02d}.*/)")


def _merge_dict(
    into: dict[str, Any], layer_name: str, layer_data: dict[str, Any], key: str
) -> list[tuple[str, str, str]]:
    """layer_data[key] 의 항목들을 into 에 합집합 머지.

    반환: 충돌 list — [(name, layer_a, layer_b)]
    (같은 이름 항목이 둘 이상 layer 에 있는 경우 모두 기록).
    같은 source 까지 같은지는 caller 에서 확인.
    """
    conflicts: list[tuple[str, str, str]] = []
    items = layer_data.get(key) or {}
    if not isinstance(items, dict):
        raise LoaderError(f"{layer_name}.{key} 가 dict 아님 (실제: {type(items).__name__})")
    for name, value in items.items():
        if name in into:
            conflicts.append((name, into.get("__source__", {}).get(name, "?"), layer_name))
        into[name] = value
    return conflicts


_INSTRUCTIONS_ALLOWED_KEYS = frozenset({"inline", "reference"})


def _validate_step_instructions(
    value: Any, pipeline_id: str, step_idx: int
) -> dict[str, str] | None:
    """step.instructions 는 객체 ({inline} XOR {reference}) 또는 None. legacy fail-loud.

    - None / 미존재 → None
    - 객체 + 키 1개 (inline 또는 reference) → 그대로 반환
    - list / string → LoaderError (구 형식 폐기)
    - 알 수 없는 키 / 키 2개 / 빈 객체 → LoaderError
    """
    if value is None:
        return None
    if isinstance(value, list):
        raise LoaderError(
            f"{pipeline_id} steps[{step_idx}].instructions 는 list 형태 폐기됨 — "
            "{inline: '...'} 또는 {reference: '@pipelines/.../*.md'} 객체로 마이그레이션 필요"
        )
    if isinstance(value, str):
        raise LoaderError(
            f"{pipeline_id} steps[{step_idx}].instructions 는 string 형태 폐기됨 — "
            "{inline: '...'} 또는 {reference: '@pipelines/.../*.md'} 객체로 마이그레이션 필요"
        )
    if not isinstance(value, dict):
        raise LoaderError(
            f"{pipeline_id} steps[{step_idx}].instructions 는 객체여야 함. "
            f"got: {type(value).__name__}"
        )
    keys = set(value.keys())
    extra = keys - _INSTRUCTIONS_ALLOWED_KEYS
    if extra:
        raise LoaderError(
            f"{pipeline_id} steps[{step_idx}].instructions 의 허용 키는 "
            f"{sorted(_INSTRUCTIONS_ALLOWED_KEYS)} 뿐. 알 수 없는 키: {sorted(extra)}"
        )
    if len(keys) != 1:
        raise LoaderError(
            f"{pipeline_id} steps[{step_idx}].instructions 객체 안에 키가 정확히 1개여야 함 "
            f"(inline XOR reference). got: {sorted(keys)}"
        )
    only_key = next(iter(keys))
    inner = value[only_key]
    if not isinstance(inner, str):
        raise LoaderError(
            f"{pipeline_id} steps[{step_idx}].instructions.{only_key} 는 string 이어야 함. "
            f"got: {type(inner).__name__}"
        )
    if only_key == "reference" and not inner.startswith("@pipelines/"):
        raise LoaderError(
            f"{pipeline_id} steps[{step_idx}].instructions.reference 는 "
            f"'@pipelines/' 로 시작해야 함. got: {inner!r}"
        )
    return {only_key: inner}


def _merge_list(into: list[Any], layer_data: dict[str, Any], key: str) -> None:
    items = layer_data.get(key) or []
    if not isinstance(items, list):
        raise LoaderError(f"{key} 가 list 아님")
    for item in items:
        if item not in into:
            into.append(item)


def load_pipeline_cascaded(
    pipeline_id: str,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """파이프라인 ID 로 P{NN}.R{NN}.{UPPER_SNAKE}.pipeline.json 을 로드하고 4-layer cascading 합성.

    합성 결과 internal shape:
        {
            "pipeline_id": "P03.R00.PRIOR_ART_SEARCH_ANALYZE",
            "persona": 3,
            "persona_prompt": "...",   # (2) persona layer 의 persona_prompt
            "common": {                 # (1)+(2)+(3) cascaded
                "inject_context": {...},
                "recommended_context": {...},
                "fragments": {...},
                "llm_tools": [...]
            },
            "dispatch_to": {...},
            "steps": [
                {
                    "effective_inject_context": {...},     # (1)+(2)+(3)+(4) cascaded
                    "effective_recommended_context": {...},
                    "effective_fragments": {...},
                    "effective_llm_tools": [...],
                    "instructions": [...] | None,
                    "tool": "..." | None,
                    "params": {...} | None,
                    "output_contract": "..." | None,
                    "description": "..."
                }
            ],
            "_filename_meta": { ... },
        }
    """
    root = root or DEFAULT_PIPELINES_ROOT
    meta = _parse_pipeline_id(pipeline_id)
    persona_dir = _find_persona_dir(root, meta["persona"])
    pipeline_file = persona_dir / f"{pipeline_id}.pipeline.json"
    pipeline_raw = _read_json(pipeline_file)

    global_file = root / "_shared" / "GLOBAL.json"
    global_data = _read_json(global_file) if global_file.exists() else {}

    persona_common_file = persona_dir / f"P{meta['persona']:02d}.COMMON.json"
    persona_data = _read_json(persona_common_file) if persona_common_file.exists() else {}

    # (1)+(2)+(3) common cascading
    cascaded_common: dict[str, Any] = {
        "inject_context": {},
        "recommended_context": {},
        "fragments": {},
        "llm_tools": [],
    }
    pipeline_common = pipeline_raw.get("common") or {}

    _merge_dict(cascaded_common["inject_context"], "GLOBAL", global_data, "inject_context")
    _merge_dict(
        cascaded_common["recommended_context"],
        "GLOBAL",
        global_data,
        "recommended_context",
    )
    _merge_dict(cascaded_common["fragments"], "GLOBAL", global_data, "fragments")
    _merge_list(cascaded_common["llm_tools"], global_data, "llm_tools")

    _merge_dict(cascaded_common["inject_context"], "persona", persona_data, "inject_context")
    _merge_dict(
        cascaded_common["recommended_context"],
        "persona",
        persona_data,
        "recommended_context",
    )
    _merge_dict(cascaded_common["fragments"], "persona", persona_data, "fragments")
    _merge_list(cascaded_common["llm_tools"], persona_data, "llm_tools")

    _merge_dict(cascaded_common["inject_context"], "pipeline", pipeline_common, "inject_context")
    _merge_dict(
        cascaded_common["recommended_context"],
        "pipeline",
        pipeline_common,
        "recommended_context",
    )
    _merge_dict(cascaded_common["fragments"], "pipeline", pipeline_common, "fragments")
    _merge_list(cascaded_common["llm_tools"], pipeline_common, "llm_tools")

    # step cascading: 각 step 에 effective_* 계산 (단일 step / 정적 병렬 묶음 둘 다 동형)
    def _cascade_one_step(step_raw: Any, step_idx: int) -> dict[str, Any]:
        if not isinstance(step_raw, dict):
            raise LoaderError(f"step 이 dict 아님: {step_raw}")
        instructions = _validate_step_instructions(
            step_raw.get("instructions"), pipeline_id, step_idx
        )
        effective_inject = dict(cascaded_common["inject_context"])
        effective_recommended = dict(cascaded_common["recommended_context"])
        effective_fragments = dict(cascaded_common["fragments"])
        effective_llm_tools = list(cascaded_common["llm_tools"])
        effective_inject.update(step_raw.get("inject_context") or {})
        effective_recommended.update(step_raw.get("recommended_context") or {})
        effective_fragments.update(step_raw.get("fragments") or {})
        for t in step_raw.get("llm_tools") or []:
            if t not in effective_llm_tools:
                effective_llm_tools.append(t)
        cascaded_step: dict[str, Any] = {
            "description": step_raw.get("description") or "",
            "instructions": instructions,
            "tool": step_raw.get("tool"),
            "params": step_raw.get("params"),
            "output_contract": step_raw.get("output_contract"),
            "effective_inject_context": effective_inject,
            "effective_recommended_context": effective_recommended,
            "effective_fragments": effective_fragments,
            "effective_llm_tools": effective_llm_tools,
        }
        # 명시 id 보존 — 없으면 walker 가 위치 인덱스 부여. 정적 병렬 묶음 sub 는 명시 id 필수
        # (같은 부모 인덱스 공유 → 충돌 방지). walker `_convert_single_step` 의 setdefault 가 honor.
        if step_raw.get("id") is not None:
            cascaded_step["id"] = step_raw["id"]
        return cascaded_step

    steps: list[Any] = []
    for step_idx, step_raw in enumerate(pipeline_raw.get("steps") or []):
        if isinstance(step_raw, list):
            # (4) step list nesting = 정적 병렬 묶음 — 각 sub 도 동일 cascading 후 **bare list** 로
            # (D-6 배관 통일: 구 `{_parallel_group}` dict-wrap 폐기 → walker list 분기·orchestrator
            # asyncio.gather 가 깨어남. sub 도 inject/fragments/llm_tools cascading 받음).
            steps.append([_cascade_one_step(sub, step_idx) for sub in step_raw])
            continue
        steps.append(_cascade_one_step(step_raw, step_idx))

    return {
        "pipeline_id": pipeline_id,
        "persona": meta["persona"],
        "persona_prompt": persona_data.get("persona_prompt") or "",
        "description": pipeline_raw.get("description") or "",
        "common": cascaded_common,
        "dispatch_to": pipeline_raw.get("dispatch_to") or {"actions": []},
        "steps": steps,
        "_filename_meta": meta,
    }


def _parse_pipeline_id(pipeline_id: str) -> dict[str, Any]:
    """P{NN}.R{NN}.{UPPER_SNAKE} → meta."""
    return parse_pipeline_filename(f"{pipeline_id}.pipeline.json")
