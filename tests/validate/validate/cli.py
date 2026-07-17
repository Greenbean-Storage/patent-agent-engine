"""validate track CLI — 15 stage 정적 검증 orchestrator (전수: 모든 구조적 파일).

  Stage 1 — Pipeline JSON schema (jsonschema Draft 7 strict)
  Stage 2 — Shared loader 4-layer cascading + effective_llm_tools
  Stage 3 — Cross-reference (pipeline ↔ contract / pipeline ↔ pipeline / instructions.reference 존재)
  Stage 4 — Tool registry 정합 (pipeline tool ↔ Actor @register)
  Stage 5 — `$.inputs.<custom>` placeholder 금지
  Stage 6 — cm:// 표기 (RFC 6901 slash 통일, dot-path 폐기)
  Stage 7 — Contracts meta-schema (@contracts/**/*.json 전수 Draft7)
  Stage 8 — Contracts extended (IOM schema + sample IOM, hard-fail)
  Stage 9 — 외부 API OpenAPI (풀 메타검증 + D6/D9/A3/A4 hygiene)
  Stage 10 — WS contract 3원 cross-consistency (ws-events ↔ asyncapi ↔ PERSONA_TO_CHANNEL)
  Stage 11 — dead contract schema 탐지 (WARN)
  Stage 12 — 인프라 설정 YAML (scaffolding / topology / compose)
  Stage 13 — asyncapi.yaml 풀 메타검증 (AsyncAPI 3.0.0 vendored)
  Stage 14 — 커버리지 census (모든 구조적 파일 검증 매핑 보장) + pyproject 정합
  Stage 15 — 정적 병렬 묶음(nested list) 형태 (D-6: 명시 id 필수·id 유일·instr XOR tool·깊이 1)

사용법:
  uv run python -m validate                                              # 전수
  uv run python -m validate --pipeline P03.R00.PRIOR_ART_SEARCH_ANALYZE   # 단일 P{NN}
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ._common import (
    PIPELINE_SCHEMA_PATH,
    PIPELINES_DIR,
    ROOT,
    ValidationReport,
    llm_tool_allowlist,
    load_global,
    load_persona_common,
    load_pipeline_schema,
)
from .stages.contracts import validate_contracts
from .stages.contracts_extended import validate_contracts_extended
from .stages.external_api import validate_external_api_spec
from .stages.stage_01_schema import validate_pipeline_schema
from .stages.stage_02_cascading import validate_cascading
from .stages.stage_03_cross_ref import validate_cross_reference
from .stages.stage_04_tool_registry import collect_actor_tool_signatures, validate_tool_registry
from .stages.stage_05_inputs_placeholder import validate_no_inputs_placeholder
from .stages.stage_06_cm_pointer import validate_cm_pointer
from .stages.stage_10_ws_consistency import validate_ws_consistency
from .stages.stage_11_dead_schema import validate_dead_schema
from .stages.stage_12_infra_config import validate_infra_config
from .stages.stage_13_asyncapi import validate_asyncapi
from .stages.stage_14_census import validate_census
from .stages.stage_15_parallel_shape import validate_parallel_shape

try:
    from venezia_pipeline_runtime.loader import parse_pipeline_filename
except ImportError as e:  # pragma: no cover
    print(f"FATAL: shared/venezia_pipeline_runtime import 실패: {e}", file=sys.stderr)
    sys.exit(2)


def _validate_one(
    file_path: Path,
    pid: str,
    schema: dict,
    allowlist: set[str],
    global_data: dict,
    all_pipeline_ids: set[str],
    tool_sigs: dict,
    rep: ValidationReport,
) -> None:
    """1개 P{NN} 파일 — Stage 1~6 순차 검증."""
    try:
        meta = parse_pipeline_filename(file_path.name)
    except Exception as e:
        rep.err(f"[{file_path.name}] 파일명 파싱 실패: {e}")
        return
    persona = int(meta["persona"])
    if meta["pipeline_id"] != pid:
        rep.err(
            f"[{file_path.name}] pipeline_id mismatch — "
            f"파일명='{meta['pipeline_id']}', expected='{pid}'"
        )
        return

    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception as e:
        rep.err(f"[{pid}] JSON 파싱 실패: {e}")
        return

    stage1_ok = validate_pipeline_schema(pid, file_path, raw, schema, rep)
    if not stage1_ok:
        return  # schema 위반이면 stage 2-5 무의미

    validate_cascading(pid, rep, allowlist)

    persona_common = load_persona_common(persona)
    if persona_common is None:
        rep.err(f"[{pid}] P{persona:02d}.COMMON.json 없음 또는 파싱 실패")
    validate_cross_reference(pid, persona, raw, global_data, persona_common, all_pipeline_ids, rep)

    validate_tool_registry(pid, raw, tool_sigs, rep)

    validate_no_inputs_placeholder(pid, raw, rep)

    validate_cm_pointer(pid, raw, rep)

    validate_parallel_shape(pid, raw, rep)


def main() -> int:
    ap = argparse.ArgumentParser(prog="validate", description="검증 track 1 — JSON 정적 정합 검증")
    ap.add_argument(
        "--pipeline",
        help="단일 pipeline_id 만 검증 (예: P03.R00.PRIOR_ART_SEARCH_ANALYZE)",
    )
    ap.add_argument("--no-warn", action="store_true", help="warning 출력 억제")
    args = ap.parse_args()

    rep = ValidationReport()

    # Stage 7/8 — Contracts (전수, pipeline 무관 1회)
    validate_contracts(rep)
    validate_contracts_extended(rep)
    # Stage 9 — 외부 API spec(OpenAPI) 위생 + 풀 메타검증 (pipeline 무관 1회)
    validate_external_api_spec(rep)
    # Stage 10-14 — WS 정합 / dead-schema / infra config / asyncapi / 커버리지 census (1회)
    validate_ws_consistency(rep)
    validate_dead_schema(rep)
    validate_infra_config(rep)
    validate_asyncapi(rep)
    validate_census(rep)

    # Stage 1-5 자원 준비
    try:
        schema = load_pipeline_schema()
    except Exception as e:
        print(f"FATAL: pipeline schema 로드 실패: {e}", file=sys.stderr)
        return 2
    try:
        allowlist = llm_tool_allowlist(schema)
    except Exception as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 2
    global_data = load_global()
    if not global_data:
        global_file = PIPELINES_DIR / "_shared" / "GLOBAL.json"
        rep.err(f"GLOBAL.json 없음 또는 빈 파일: {global_file}")
    tool_sigs = collect_actor_tool_signatures()

    # 모든 P{NN} 수집
    all_pipeline_ids: set[str] = set()
    pipeline_files: list[Path] = []
    for f in sorted(PIPELINES_DIR.glob("**/*.pipeline.json")):
        try:
            meta = parse_pipeline_filename(f.name)
        except Exception:
            rep.err(f"[{f.relative_to(PIPELINES_DIR)}] non-P{{NN}} 파일 (구설계 잔재)")
            continue
        all_pipeline_ids.add(meta["pipeline_id"])
        pipeline_files.append(f)

    # 각 pipeline 검증
    for f in pipeline_files:
        meta = parse_pipeline_filename(f.name)
        pid = meta["pipeline_id"]
        if args.pipeline and pid != args.pipeline:
            continue
        rep.checked += 1
        _validate_one(f, pid, schema, allowlist, global_data, all_pipeline_ids, tool_sigs, rep)

    return _emit_report(rep, allowlist, all_pipeline_ids, tool_sigs, no_warn=args.no_warn)


def _emit_report(
    rep: ValidationReport,
    allowlist: set[str],
    all_pipeline_ids: set[str],
    tool_sigs: dict,
    no_warn: bool,
) -> int:
    bar = "━" * 78
    print(bar)
    print("  validate — JSON 산출물 schema · cross-ref · tool registry 정적 검증")
    print(bar)
    print()
    print(f"  pipeline schema : {PIPELINE_SCHEMA_PATH.relative_to(ROOT)}")
    print(
        f"  pipelines root  : {PIPELINES_DIR.relative_to(ROOT)} "
        f"({len(all_pipeline_ids)} P{{NN}} 파일)"
    )
    print(f"  llm_tools enum  : {sorted(allowlist)}")
    print(f"  Actor tools     : 300.Actor/src/tools/ ({len(tool_sigs)} @register)")
    print()
    print(f"  Pipelines checked: {rep.checked}")
    print()

    sp = rep.stage_pass
    items = [
        ("Stage 1 — schema (jsonschema)        ", sp["schema (jsonschema)"], rep.checked),
        ("Stage 2 — cascading (shared loader)  ", sp["cascading (shared loader)"], rep.checked),
        ("Stage 3 — cross-reference            ", sp["cross-reference"], rep.checked),
        ("Stage 4 — tool registry              ", sp["tool registry"], rep.checked),
        ("Stage 5 — no inputs placeholder      ", sp["no inputs placeholder"], rep.checked),
        ("Stage 6 — cm:// pointer notation     ", sp["cm:// pointer notation"], rep.checked),
        ("Stage 7 — contracts meta-schema (전수)", sp["contracts (meta-schema)"], 1),
        ("Stage 8 — contracts extended (IOM)   ", sp["contracts extended (IOM)"], 1),
        ("Stage 9 — external_api OpenAPI (풀)   ", sp["external_api spec"], 1),
        ("Stage 10 — WS 3원 cross-consistency  ", sp["ws consistency"], 1),
        ("Stage 11 — dead schema (warn)        ", sp["dead schema"], 1),
        ("Stage 12 — infra config (yaml)       ", sp["infra config"], 1),
        ("Stage 13 — asyncapi meta-schema      ", sp["asyncapi spec"], 1),
        ("Stage 14 — coverage census (전부)    ", sp["coverage census"], 1),
        ("Stage 15 — parallel shape (병렬 묶음)", sp["parallel shape"], rep.checked),
    ]
    for label, passed, total in items:
        mark = "✓" if passed == total else "✗"
        print(f"  {mark} {label}: {passed:>3} / {total:<3} pass")
    print(bar)
    print()

    if rep.errors:
        print(f"❌ {len(rep.errors)} error(s):")
        for e in rep.errors:
            print(f"  {e}")
    if rep.warnings and not no_warn:
        print(f"\n⚠️  {len(rep.warnings)} warning(s):")
        for w in rep.warnings:
            print(f"  {w}")

    if rep.ok:
        print("✅ validate PASS — 15 stage 모두 통과.")
        return 0
    print(f"❌ validate FAIL — {len(rep.errors)} error(s).")
    return 1
