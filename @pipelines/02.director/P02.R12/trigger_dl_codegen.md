# P02.R12.DRAWING_ORCHESTRATION :: trigger_dl_codegen

> 도면 DL 코드 생성 작업의 trigger + 결과 consolidation.

## Instructions

1. drawings_with_numerals 의 각 도면 type + chosen_tool 결정.

2. 실제 DL 코드는 next chain (P05.R00.GENERATE_DL) 에서 생성.

3. dl_generation_plan 출력 — 각 도면의 {drawing_id, type, chosen_tool_hint, render_format}.

## Output Contract

`dl-generation-plan-output`
