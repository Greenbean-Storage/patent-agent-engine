# P02.R12.DRAWING_ORCHESTRATION :: trigger_vision_check

> vision 검수 작업의 trigger.

## Instructions

1. drawings_with_figure 의 figure_bytes_b64 list 를 next chain (P06.R00.REVIEW_DRAWING) 에 전달 준비.

2. inspect_plan 출력 — 각 도면의 {drawing_id, figure_b64, mime_type} list.

## Output Contract

`inspect-plan-output`
