# P02.R12.DRAWING_ORCHESTRATION :: trigger_claims_mapping

> 청구항-부호 매핑 작업의 trigger + 결과 consolidation.

## Instructions

1. drawings_with_numerals 와 IOM.claims 를 보고 부호-청구항 매핑 plan 수립.

2. 실제 매핑은 next chain (P04.R11.CLAIMS_WITH_NUMERALS) 에서 수행.

3. claims_mapping_plan 출력 — 각 청구항의 element ↔ 부호 매핑 계획.

## Output Contract

`claims-mapping-plan-output`
