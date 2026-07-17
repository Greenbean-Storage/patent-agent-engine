"""validate 의 15 stage 모듈.

stage_01_schema           — jsonschema Draft 7 strict (raw pipeline JSON)
stage_02_cascading        — 4-layer cascading 후 effective_llm_tools
stage_03_cross_ref        — pipeline ↔ contract / pipeline / instructions.reference 존재
stage_04_tool_registry    — pipeline tool step ↔ Actor `@register` 정합
stage_05_inputs_placeholder — `$.inputs.<custom>` 금지
stage_06_cm_pointer       — cm:// 표기 (RFC 6901 slash 통일, dot-path 폐기)
contracts                  — @contracts/**/*.json 전수 meta-schema
contracts_extended         — IOM schema + sample IOM (hard-fail)
external_api               — openapi.nexus.json 풀 메타검증 + hygiene
stage_10_ws_consistency    — ws-events ↔ asyncapi ↔ PERSONA_TO_CHANNEL 3원 일치
stage_11_dead_schema       — 미참조 contract schema 탐지 (WARN)
stage_12_infra_config      — scaffolding / topology / compose YAML 정합
stage_13_asyncapi          — asyncapi.yaml 풀 메타검증 (AsyncAPI 3.0.0 vendored)
stage_14_census            — 구조적 파일 검증 커버리지 census + pyproject 정합
stage_15_parallel_shape    — 정적 병렬 묶음(nested list) 형태 (D-6: 명시 id·유일·instr XOR tool·깊이1)
"""
