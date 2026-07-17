# tests/validate

## 목적
JSON 산출물 (pipeline / contract / 4-layer cascading 결과) 의 schema 정합과 cross-reference 정합을 코드 실행 없이 정적 검증.

## scope
- 22 P{NN}.R{NN}.*.pipeline.json
- @contracts/_shared/pipeline-definition.schema.json (jsonschema Draft 7 strict)
- @contracts/<persona>/stages/*.schema.json (step output_contract cross-ref)
- 4-layer cascading 머지 결과의 effective_llm_tools (self-chain fetch_* allowlist)
- 300.Actor/src/tools/**/*.py 의 @register 데코레이터 ↔ pipeline tool step
- step.output / dispatch_choice / dispatch_to.actions 연결 정합
- $.inputs.<custom> placeholder 금지
- cm:// pointer 표기 (RFC 6901 slash 통일, dot-path 폐기)
- @contracts/**/*.json 전수 meta-schema + IOM extended (sample IOM, hard-fail)
- 외부 API spec — openapi.nexus.json 풀 메타검증(openapi-spec-validator) + asyncapi.yaml (AsyncAPI 3.0 vendored) + WS contract 3원 cross-consistency
- 인프라 설정 YAML (scaffolding / topology / compose / knobs / **engine.config** — engine-config.schema.json 검증 + persona-id 4원 정합 게이트) · dead schema 탐지(WARN) · 커버리지 census

## 호출
```
make validate                                                 # 22 P{NN} + 전 구조적 파일 전수 (15 stage)
cd tests/validate && uv run python -m validate --pipeline P03.R00.PRIOR_ART_SEARCH_ANALYZE
```

## 의존
- `jsonschema>=4.23.0` (Draft 7 strict)
- `pyyaml>=6.0`
- `openapi-spec-validator>=0.7.1` (Stage 9 — OpenAPI 풀 메타검증)
- `shared/venezia_pipeline_runtime` (loader 재사용 — composer/dispatch_resolver 는 Actor/DRO 로 흡수됨)

## 산출
stdout PASS/FAIL 표시 + 실패 stage·item 목록. exit 0 (success) / 1 (validation failed).
