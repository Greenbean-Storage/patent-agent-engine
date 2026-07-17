# P02.R12.DRAWING_ORCHESTRATION :: trigger_render

> 도면 렌더링 작업의 trigger + 결과 consolidation.

## Instructions

1. drawings_with_dl 의 각 도면 dl_code 를 보고 렌더링 plan 수립.

2. 실제 렌더링은 next chain (P05.R10.RENDER_DRAWING) 또는 DRO tool step 에서 수행.

3. render_plan 출력 — 각 도면의 {drawing_id, chosen_tool, dl_code} list.

## Output Contract

`render-plan-output`
