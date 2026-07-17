# P02.R12.DRAWING_ORCHESTRATION :: trigger_numerals

> 도면별 numerals 추출 작업의 trigger + 결과 consolidation.

## Instructions

1. context.steps.review_drawing_list.drawings 목록을 보고 각 도면에 필요한 부호 추출 작업 계획.

2. 실제 추출은 next chain (P04.R10.EXTRACT_NUMERALS) 에서 수행 — 본 step 은 plan 만.

3. drawings_for_numerals 배열 출력 — 각 element: {drawing_id, key_elements, expected_numeral_count}.

## Output Contract

`drawings-for-numerals-plan-output`
