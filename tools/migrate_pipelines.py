# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""W{NN} → P{NN} 자동 마이그레이션 도구.

처리:
- llm_task → P{NN} LLM step (instructions, output_contract)
- parallel_task multi → list nesting (정적 병렬)
- parallel_task fan_out + service → 1 step (도구가 list 처리)
- api_call → P{NN} tool step
- http_response → 폐기 (chain trail 에 자동 저장)
- sequential_conditional → dispatch_to.actions 변환 (마지막 step 가 dispatch_choice 출력)
- agentic_llm_loop → 1 LLM step + dispatch_to (cross-persona 도구는 chain dispatch)

각 step.output (inline dict) → @contracts/<persona>/stages/<step_id>-output.schema.json 자동 생성.

수동 보완 필요한 케이스 (tricky):
- review→regenerate loop (W02.R12)
- per-item fan_out + sub_pipeline (W01.R10, W02.R12)

사용:
    uv run tools/migrate_pipelines.py <input_W_file> <output_P_dir>
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

PERSONA_NAMES = {
    1: "buddy",
    2: "director",
    3: "finder",
    4: "thinker",
    5: "crafter",
    6: "inspector",
}
PERSONA_DIRS = {
    1: "01.buddy",
    2: "02.director",
    3: "03.finder",
    4: "04.thinker",
    5: "05.crafter",
    6: "06.inspector",
}


def to_upper_snake(title: str) -> str:
    """e.g. 'chat-conversation' → 'CHAT_CONVERSATION'"""
    return re.sub(r"[^A-Z0-9]+", "_", title.upper()).strip("_")


def parse_output_to_schema(out_spec: Any) -> dict[str, Any]:
    """W{NN} step.output (inline dict) → JSON Schema."""
    if not isinstance(out_spec, dict):
        return {"type": "object"}
    props: dict[str, Any] = {}
    required: list[str] = []
    for k, v in out_spec.items():
        if isinstance(v, str):
            t = v.lower()
            if "string" in t and "[" in v:
                # e.g. "string[]"
                props[k] = {"type": "array", "items": {"type": "string"}}
            elif "[" in v and "{" in v:
                # e.g. "[{a: string, b: int}]" — list of objects, skip parse
                props[k] = {"type": "array", "items": {"type": "object"}}
            elif "int" in t:
                props[k] = {"type": "integer"}
            elif "float" in t or "number" in t:
                props[k] = {"type": "number"}
            elif "bool" in t:
                props[k] = {"type": "boolean"}
            elif "object" in t:
                props[k] = {"type": "object"}
            elif "|null" in v or "nullable" in t:
                props[k] = {"type": "string", "nullable": True}
            else:
                props[k] = {"type": "string"}
        elif isinstance(v, dict):
            props[k] = {"type": "object"}
        elif isinstance(v, list):
            props[k] = {"type": "array"}
        else:
            props[k] = {"type": "string"}
        required.append(k)
    return {
        "type": "object",
        "properties": props,
        "required": required,
    }


def migrate_llm_step(
    step: dict[str, Any], idx: int, persona_dir: Path, persona: int
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """W{NN} llm_task step → P{NN} step + (optional) contract schema."""
    step_id = step.get("id", f"step_{idx}")
    contract_id = step.get("output_contract") or f"{step_id.replace('_', '-')}-output"
    new_step: dict[str, Any] = {
        "description": step.get("description") or step.get("name") or "",
        "inject_context": {},
        "recommended_context": {},
        "fragments": {},
        "instructions": step.get("instructions") or [],
        "llm_tools": [],
        "output_contract": contract_id,
    }
    # output schema generation (from step.output inline)
    schema = None
    if step.get("output"):
        schema = parse_output_to_schema(step["output"])
    return new_step, schema


def migrate_pipeline(
    input_path: Path, pipelines_root: Path, contracts_root: Path
) -> list[Path]:
    """W{NN} 파일 1개 → P{NN} 파일 N개 (loop split 등) + contracts 작성."""
    data = json.loads(input_path.read_text(encoding="utf-8"))
    persona: int = data["persona"]
    pipeline_id: str = data["pipeline_id"]
    title = to_upper_snake(pipeline_id)
    persona_dir_name = PERSONA_DIRS[persona]
    persona_dir = pipelines_root / persona_dir_name

    # filename 의 R 번호 — 원본 W{NN}.R{NN}.title 에서 추출 ('W' → 'P')
    fname_match = re.match(r"^W(\d{2})\.(R\d{2})\.", input_path.name)
    role = fname_match.group(2) if fname_match else "R00"
    p_filename = f"P{persona:02d}.{role}.{title}.pipeline.json"

    # contracts dir
    contracts_persona_dir = contracts_root / persona_dir_name / "stages"
    contracts_persona_dir.mkdir(parents=True, exist_ok=True)

    new_pipeline: dict[str, Any] = {
        "description": data.get("description") or "",
        "common": {
            "inject_context": {},
            "recommended_context": {},
            "fragments": {},
            "llm_tools": [],
        },
        "dispatch_to": None,
        "steps": [],
    }

    schemas_to_write: dict[str, dict] = {}

    for idx, step in enumerate(data.get("steps") or []):
        stype = step.get("type")
        if stype in ("llm_task", "agentic_llm_loop"):
            new_step, schema = migrate_llm_step(step, idx, persona_dir, persona)
            new_pipeline["steps"].append(new_step)
            if schema:
                schemas_to_write[new_step["output_contract"]] = schema
        elif stype == "parallel_task":
            mode = step.get("mode")
            tasks = step.get("tasks") or []
            if mode == "multi" and len(tasks) == 1:
                # single multi task — DRO tool step
                task = tasks[0]
                if "service" in task:
                    svc = task["service"]
                    action = task.get("action", "*")
                    tool_name = f"{svc}.{action}"
                    new_step = {
                        "description": step.get("description")
                        or step.get("name")
                        or "",
                        "inject_context": {},
                        "recommended_context": {},
                        "fragments": {},
                        "tool": tool_name,
                        "params": task.get("params_map") or {},
                        "output_contract": step.get("output_contract")
                        or f"{step.get('id', f'step_{idx}')}-output",
                    }
                    new_pipeline["steps"].append(new_step)
                    if step.get("output"):
                        schemas_to_write[new_step["output_contract"]] = (
                            parse_output_to_schema(step["output"])
                        )
                else:
                    # sub_pipeline single — flag as TODO
                    new_pipeline["steps"].append(
                        {
                            "_TODO": f"parallel_task multi+sub_pipeline 수동 변환 필요 (chain dispatch 로): {task.get('sub_pipeline')}",
                            "description": step.get("description") or "",
                        }
                    )
            elif mode == "fan_out":
                # fan_out — 1 step + 도구 list 처리 (kipris 패턴) 또는 sub_pipeline per item 분리
                task = step.get("task") or {}
                if "service" in task:
                    svc = task["service"]
                    action = task.get("action", "*")
                    tool_name = f"{svc}.{action}"
                    new_step = {
                        "description": (step.get("description") or "")
                        + " — fan_out → 1 step + 도구가 list 내부 처리",
                        "inject_context": {},
                        "recommended_context": {},
                        "fragments": {},
                        "tool": tool_name,
                        "params": task.get("params_map") or {},
                        "output_contract": step.get("output_contract")
                        or f"{step.get('id', f'step_{idx}')}-output",
                    }
                    new_pipeline["steps"].append(new_step)
                    if step.get("output"):
                        schemas_to_write[new_step["output_contract"]] = (
                            parse_output_to_schema(step["output"])
                        )
                elif "sub_pipeline" in task:
                    new_pipeline["steps"].append(
                        {
                            "_TODO": f"fan_out + sub_pipeline per item 수동 변환 필요 (chain self-recursion 또는 multimodal 통합): {task.get('sub_pipeline')}",
                            "description": step.get("description") or "",
                        }
                    )
            else:
                new_pipeline["steps"].append(
                    {
                        "_TODO": f"parallel_task mode={mode} 수동 검토 필요",
                        "description": step.get("description") or "",
                    }
                )
        elif stype == "api_call":
            # CM read/write — DRO tool step (cm.api_call 등 추후 도구 등록 필요)
            new_pipeline["steps"].append(
                {
                    "_TODO": "api_call → DRO tool step (cm.* 도구 등록 필요) 또는 composer inject_context",
                    "description": step.get("description") or "",
                    "calls": step.get("calls") or [],
                }
            )
        elif stype == "http_response":
            # 폐기 — chain trail 자동 저장
            pass
        elif stype == "sequential_conditional":
            # dispatch_to.actions 로 변환
            branches = step.get("branches") or []
            actions = []
            for br in branches:
                sub = br.get("sub_pipeline")
                if sub:
                    actions.append([f"_TODO_RENAME_TO_P_{sub}"])
                else:
                    actions.append([])
            new_pipeline["dispatch_to"] = {
                "_TODO": "sequential_conditional → dispatch_to.actions. 마지막 LLM step 의 output_contract 에 dispatch_choice (integer enum) 추가 필요.",
                "actions": actions,
            }
        else:
            new_pipeline["steps"].append(
                {
                    "_TODO": f"step.type={stype} 수동 변환",
                    "description": step.get("description") or "",
                }
            )

    # write pipeline file
    output_path = persona_dir / p_filename
    output_path.write_text(
        json.dumps(new_pipeline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # write schemas
    written = [output_path]
    for cid, schema in schemas_to_write.items():
        sf = contracts_persona_dir / f"{cid}.schema.json"
        sf.write_text(
            json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        written.append(sf)

    return written


def main():
    if len(sys.argv) < 2:
        print(
            "Usage: migrate_pipelines.py <W{NN}.R{NN}.*.pipeline.json> [..more files]"
        )
        sys.exit(1)
    repo = Path(__file__).resolve().parents[1]
    pipelines_root = repo / "@pipelines"
    contracts_root = repo / "@contracts"
    for arg in sys.argv[1:]:
        in_path = Path(arg)
        if not in_path.is_absolute():
            in_path = repo / in_path
        outs = migrate_pipeline(in_path, pipelines_root, contracts_root)
        print(f"[migrated] {in_path.name} → {len(outs)} files")
        for o in outs:
            print(f"  {o.relative_to(repo)}")


if __name__ == "__main__":
    main()
